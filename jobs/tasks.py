"""Job entry points shared by the scheduler, the CLI and the dashboard's refresh button.

Every job opens its own DB connection, logs to fetch_logs, and never lets an exception from
one source/job propagate into another.
"""
from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Callable

from config.settings import Settings, get_settings, load_yaml
from database.connection import connect
from database.migrate import migrate
from database.repository import Repository
from processing.entities import build_alias_map
from processing.pipeline import ProcessingContext, build_context, process_items
from sources.base import SourceConfig, SourceStatus
from sources.registry import build_source, load_source_configs
from utils.http import BlockedError, HttpClient, RateLimitedError, RobotsDisallowedError
from utils.timeutils import UTC, is_market_hours, now_iso, now_utc, parse_datetime, to_iso

log = logging.getLogger(__name__)

_client: HttpClient | None = None
MAX_BACKOFF = timedelta(hours=6)


def http_client(settings: Settings | None = None) -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient(settings or get_settings())
    return _client


def open_repo() -> Repository:
    return Repository(connect())


def init_database() -> None:
    conn = connect()
    try:
        migrate(conn)
        Repository(conn).sync_sources(load_source_configs())
    finally:
        conn.close()


def _run_logged(job: str, fn: Callable[[Repository], dict[str, Any]], source_name: str | None = None) -> dict[str, Any]:
    repo = open_repo()
    started, t0 = now_iso(), time.monotonic()
    source_id = repo.ensure_source(source_name, "SYSTEM") if source_name else None
    try:
        result = fn(repo)
        status = "SUCCESS"
        error = None
        if source_id:
            repo.record_source_result(source_id, SourceStatus.ACTIVE.value, success=True)
    except Exception as exc:
        log.exception("job %s failed", job)
        result, status, error = {"error": str(exc)}, "FAILED", "".join(traceback.format_exception_only(exc)).strip()
        if source_id:
            repo.record_source_result(source_id, SourceStatus.FAILED.value, error=error)
    repo.log_fetch(source_id=source_id, job=job, started_at=started, finished_at=now_iso(), status=status,
                   error=error, duration_ms=int((time.monotonic() - t0) * 1000))
    repo.conn.close()
    return result


# ------------------------------------------------------------------------------ market data jobs
def run_universe_job() -> dict[str, Any]:
    from nse.fo_universe import refresh_universe
    from nse.reference import fetch_reference_data

    settings = get_settings()

    def work(repo: Repository) -> dict[str, Any]:
        result = refresh_universe(repo, http_client(settings), settings)
        ref = fetch_reference_data(http_client(settings))
        result["reference_updated"] = repo.update_reference_data(ref)
        stocks = [(s["id"], s["symbol"], s["name"]) for s in repo.active_stocks()]
        curated = {str(k): [str(a) for a in v] for k, v in load_yaml("aliases.yaml").get("aliases", {}).items()}
        repo.replace_aliases(build_alias_map(stocks, curated))
        repo.set_state("universe_refreshed_at", now_iso())
        return result

    return _run_logged("universe", work, "NSE F&O Universe")


def run_prices_job() -> dict[str, Any]:
    from nse.fo_activity import refresh_fo_activity
    from nse.prices import refresh_prices
    from technical.screener import run_daily_screen

    settings = get_settings()

    def work(repo: Repository) -> dict[str, Any]:
        result = refresh_prices(repo, http_client(settings), settings)
        try:
            result.update(refresh_fo_activity(repo, http_client(settings)))
        except Exception as exc:
            log.exception("F&O activity refresh failed")
            result["fo_activity_error"] = str(exc)
        result.update(run_daily_screen(repo))
        # A run where NSE was unreachable is not a refresh, so the worker's catch-up will retry it.
        if not result.get("errors"):
            repo.set_state("prices_refreshed_at", now_iso())
        return result

    return _run_logged("prices", work, "NSE EOD Data")


def run_intraday_technical_job() -> dict[str, Any]:
    from nse.live_indices import refresh_live_indices
    from technical.screener import run_intraday_screen

    def work(repo: Repository) -> dict[str, Any]:
        result = run_intraday_screen(repo)
        try:  # official NSE levels overwrite the Yahoo fallback rows
            result.update(refresh_live_indices(repo, http_client()))
        except Exception as exc:
            log.warning("NSE live indices failed, keeping Yahoo levels: %s", exc)
            result["nse_live_error"] = str(exc)
        repo.set_state("intraday_refreshed_at", now_iso())
        return result

    return _run_logged("technical_intraday", work, "Intraday Bars (yfinance)")


def run_fundamentals_job() -> dict[str, Any]:
    from analysis.fundamentals import refresh_fundamentals

    def work(repo: Repository) -> dict[str, Any]:
        result = refresh_fundamentals(repo)
        repo.set_state("fundamentals_refreshed_at", now_iso())
        return result

    return _run_logged("fundamentals", work, "Fundamentals (yfinance)")


def run_market_snapshot_job() -> dict[str, Any]:
    from analysis.market import run_market_snapshot

    def work(repo: Repository) -> dict[str, Any]:
        result = run_market_snapshot(repo, get_settings())
        repo.set_state("market_snapshot_at", now_iso())
        return result

    return _run_logged("market_snapshot", work)


def run_maintenance_job() -> dict[str, Any]:
    settings = get_settings()

    def work(repo: Repository) -> dict[str, Any]:
        purged = repo.purge_old_snippets(settings.news_retention_days)
        cutoff = to_iso(now_utc() - timedelta(days=90))
        repo.conn.execute("DELETE FROM fetch_logs WHERE started_at < ?", (cutoff,))
        repo.conn.execute("DELETE FROM market_snapshots WHERE taken_at < ?", (cutoff,))
        return {"snippets_purged": purged}

    return _run_logged("maintenance", work)


# ------------------------------------------------------------------------------ news
def _effective_interval(cfg: SourceConfig) -> timedelta:
    minutes = cfg.interval_minutes if is_market_hours() else min(cfg.interval_minutes * 3, 60)
    return timedelta(minutes=minutes)


def _is_due(cfg: SourceConfig, row) -> bool:
    now = now_utc()
    if row is None or not cfg.enabled:
        return cfg.enabled
    next_allowed = parse_datetime(row["next_allowed_fetch_at"], assume_tz=UTC)
    if next_allowed and now < next_allowed:
        return False
    last = parse_datetime(row["last_attempt_at"], assume_tz=UTC)
    return last is None or now - last >= _effective_interval(cfg)


def _backoff(cfg: SourceConfig, failures: int, retry_after: float | None = None) -> timedelta:
    if retry_after:
        return timedelta(seconds=retry_after)
    return min(timedelta(minutes=cfg.interval_minutes) * (2 ** min(failures, 8)), MAX_BACKOFF)


def run_source(cfg: SourceConfig, ctx: ProcessingContext) -> dict[str, Any]:
    """Fetch + process one source. Never raises."""
    settings = get_settings()
    repo = open_repo()
    try:
        row = repo.get_source(cfg.name)
        source_id = row["id"]
        failures = row["consecutive_failures"]
        started, t0 = now_iso(), time.monotonic()
        stats: dict[str, int] = {}
        error: str | None = None
        try:
            outcome = build_source(cfg, http_client(settings), settings).fetch()
            stats = process_items(repo, source_id, outcome.items, ctx)
            status = SourceStatus.ACTIVE if (outcome.items or outcome.not_modified) else SourceStatus.NO_DATA
            if outcome.feed_errors:
                error = "; ".join(outcome.feed_errors)
            repo.record_source_result(source_id, status.value, success=True)
            if error:
                repo.conn.execute("UPDATE sources SET last_error = ? WHERE id = ?", (f"partial: {error}"[:2000], source_id))
        except RateLimitedError as exc:
            status, error = SourceStatus.RATE_LIMITED, str(exc)
            repo.record_source_result(source_id, status.value, error=error,
                                      next_allowed=now_utc() + _backoff(cfg, failures, exc.retry_after))
        except (RobotsDisallowedError, BlockedError) as exc:
            status, error = SourceStatus.BLOCKED, str(exc)
            repo.record_source_result(source_id, status.value, error=error, next_allowed=now_utc() + MAX_BACKOFF)
        except Exception as exc:
            log.exception("[%s] source run failed", cfg.name)
            status, error = SourceStatus.FAILED, f"{type(exc).__name__}: {exc}"
            repo.record_source_result(source_id, status.value, error=error,
                                      next_allowed=now_utc() + _backoff(cfg, failures + 1))
        repo.log_fetch(
            source_id=source_id, job="news", started_at=started, finished_at=now_iso(), status=status.value,
            items_fetched=stats.get("fetched", 0), items_new=stats.get("new", 0),
            items_duplicate=stats.get("duplicate", 0), items_irrelevant=stats.get("irrelevant", 0),
            recs_extracted=stats.get("recs", 0), error=(error or "")[:2000] or None,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        log.info("[%s] %s %s", cfg.name, status.value, stats)
        return {"source": cfg.name, "status": status.value, **stats}
    except Exception as exc:  # last-resort guard (e.g. database locked)
        log.exception("[%s] unexpected failure", cfg.name)
        return {"source": cfg.name, "status": "FAILED", "error": str(exc)}
    finally:
        repo.conn.close()


def run_news_job(force: bool = False, only: str | None = None, max_workers: int = 4) -> list[dict[str, Any]]:
    configs = [c for c in load_source_configs() if c.enabled and (only is None or c.name == only)]
    repo = open_repo()
    try:
        ctx = build_context(repo, get_settings())
        due = configs if force else [c for c in configs if _is_due(c, repo.get_source(c.name))]
    finally:
        repo.conn.close()
    if not due:
        return []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="src") as pool:
        results = list(pool.map(lambda c: run_source(c, ctx), due))
    repo = open_repo()
    repo.set_state("news_refreshed_at", now_iso())
    repo.conn.close()
    return results

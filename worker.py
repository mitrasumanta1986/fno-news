"""Ingestion worker.

    python worker.py                  # run the scheduler (keeps running)
    python worker.py --once           # run every job once and exit
    python worker.py --once --job news [--source "CNBC-TV18"]
    python worker.py --init           # create/migrate the database only

Jobs: universe | prices | news | technical | fundamentals | market | maintenance | all
"""
from __future__ import annotations

import argparse
import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import get_settings, load_yaml
from jobs import tasks
from utils.logging_setup import setup_logging
from utils.timeutils import IST, UTC, now_utc, parse_datetime

log = logging.getLogger("worker")


def _stale(repo_key: str, hours: float) -> bool:
    repo = tasks.open_repo()
    try:
        value = repo.get_state(repo_key)
    finally:
        repo.conn.close()
    last = parse_datetime(value, assume_tz=UTC) if value else None
    return last is None or (now_utc() - last).total_seconds() > hours * 3600


def run_once(job: str, source: str | None) -> None:
    if job in ("universe", "all"):
        print("universe:", tasks.run_universe_job())
    if job in ("prices", "all"):
        print("prices:", tasks.run_prices_job())
    if job in ("technical", "all"):
        print("technical:", tasks.run_intraday_technical_job())
    if job in ("news", "all"):
        for result in tasks.run_news_job(force=True, only=source):
            print("news:", result)
    if job in ("fundamentals", "all"):
        print("fundamentals:", tasks.run_fundamentals_job())
    if job in ("market", "all"):
        print("market snapshot:", tasks.run_market_snapshot_job())
    if job in ("maintenance",):
        print("maintenance:", tasks.run_maintenance_job())


def _eod_behind() -> bool:
    from nse.prices import last_expected_trade_date

    repo = tasks.open_repo()
    try:
        latest = repo.conn.execute("SELECT MAX(trade_date) FROM price_history").fetchone()[0]
    finally:
        repo.conn.close()
    return latest is None or latest < last_expected_trade_date().isoformat()


def _eod_catch_up() -> None:
    """Covers evening runs missed while the PC was off, and runs where NSE was unreachable.
    On an exchange holiday this just finds no file (404) and tries again next hour."""
    if _eod_behind():
        log.info("EOD data is behind; running prices catch-up")
        tasks.run_prices_job()


def _intraday_tick() -> None:
    from technical.screener import intraday_session_active

    if intraday_session_active():
        tasks.run_intraday_technical_job()


def run_scheduler() -> None:
    if _stale("universe_refreshed_at", 20):
        tasks.run_universe_job()
    if _stale("prices_refreshed_at", 24) or _eod_behind():
        tasks.run_prices_job()
    if _stale("fundamentals_refreshed_at", 24):
        tasks.run_fundamentals_job()

    refresh = int(load_yaml("technical.yaml").get("intraday", {}).get("refresh_minutes", 5))
    scheduler = BlockingScheduler(timezone=IST, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300})
    scheduler.add_job(tasks.run_news_job, IntervalTrigger(minutes=1), id="news_tick", name="news (due sources)")
    scheduler.add_job(_intraday_tick, IntervalTrigger(minutes=refresh), id="technical_intraday")
    scheduler.add_job(tasks.run_universe_job, CronTrigger(hour=8, minute=0), id="universe")
    scheduler.add_job(tasks.run_prices_job, CronTrigger(day_of_week="mon-fri", hour="18,20,22", minute=45), id="prices")
    scheduler.add_job(_eod_catch_up, CronTrigger(minute=50), id="prices_catch_up")
    scheduler.add_job(tasks.run_fundamentals_job, CronTrigger(day_of_week="mon-fri", hour=7, minute=30), id="fundamentals")
    # Market analysis: every hour on the hour, 09:00-16:00 IST, trading days
    scheduler.add_job(tasks.run_market_snapshot_job, CronTrigger(day_of_week="mon-fri", hour="9-16", minute=0),
                      id="market_snapshot")
    scheduler.add_job(tasks.run_maintenance_job, CronTrigger(hour=2, minute=30), id="maintenance")
    log.info("scheduler started; Ctrl+C to stop")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F&O News & Research Dashboard ingestion worker")
    parser.add_argument("--once", action="store_true", help="run jobs once and exit")
    parser.add_argument("--init", action="store_true", help="create/migrate the database and exit")
    parser.add_argument("--job", default="all", choices=["all", "universe", "prices", "news", "technical", "fundamentals",
                                                          "market", "maintenance"])
    parser.add_argument("--source", help="with --job news: run only this source (name as in sources.yaml)")
    args = parser.parse_args(argv)

    setup_logging("worker")
    get_settings().cache_dir.mkdir(parents=True, exist_ok=True)
    tasks.init_database()
    if args.init:
        print("database ready:", get_settings().db_path)
        return 0
    if args.once:
        run_once(args.job, args.source)
        return 0
    run_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())

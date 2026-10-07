"""Official NSE end-of-day data: CM bhavcopy (UDiFF format) and all-index closing file.

These are EOD values. The dashboard always labels prices with their trade date.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta

from config.settings import Settings
from database.repository import Repository
from utils.http import FetchError, HttpClient
from utils.timeutils import now_ist

log = logging.getLogger(__name__)

CM_BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
INDEX_CLOSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
EQUITY_SERIES = {"EQ", "BE", "BZ"}


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value in ("", "-"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_cm_bhavcopy(zip_bytes: bytes, symbol_ids: dict[str, int]) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        symbol = (r.get("TckrSymb") or "").strip().upper()
        if symbol not in symbol_ids or (r.get("SctySrs") or "").strip() not in EQUITY_SERIES:
            continue
        volume = _num(r.get("TtlTradgVol"))
        rows.append({
            "stock_id": symbol_ids[symbol],
            "trade_date": (r.get("TradDt") or "").strip(),
            "open": _num(r.get("OpnPric")), "high": _num(r.get("HghPric")), "low": _num(r.get("LwPric")),
            "close": _num(r.get("ClsPric")), "prev_close": _num(r.get("PrvsClsgPric")),
            "volume": int(volume) if volume is not None else None,
            "source": "NSE CM bhavcopy (EOD)",
        })
    return rows


def parse_index_close(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        name = r.get("Index Name")
        try:
            trade_date = datetime.strptime(r.get("Index Date", ""), "%d-%m-%Y").date().isoformat()
        except ValueError:
            continue
        if not name:
            continue
        rows.append({
            "index_name": name, "trade_date": trade_date, "close": _num(r.get("Closing Index Value")),
            "change": _num(r.get("Points Change")), "change_pct": _num(r.get("Change(%)")),
            "source": "NSE indices (EOD)",
        })
    return rows


def _candidate_dates(lookback_calendar_days: int) -> list[date]:
    now = now_ist()
    # Bhavcopy is published in the evening; don't request today's before 18:00 IST.
    start = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    days = [start - timedelta(days=i) for i in range(lookback_calendar_days)]
    return [d for d in days if d.weekday() < 5]


def refresh_prices(repo: Repository, client: HttpClient, settings: Settings) -> dict:
    symbol_ids = {r["symbol"]: r["id"] for r in repo.active_stocks()}
    if not symbol_ids:
        raise RuntimeError("F&O universe is empty; run the universe job first")
    have_prices, have_index = repo.price_dates(), repo.index_dates()
    target_days = settings.price_backfill_days
    lookback = 7 if len(have_prices) >= target_days else int(target_days * 1.6) + 10

    loaded, index_loaded, missing, errors = [], [], [], []
    for d in _candidate_dates(lookback):
        iso = d.isoformat()
        if iso not in have_prices:
            try:
                rows = parse_cm_bhavcopy(client.get(CM_BHAV_URL.format(d=d)).content, symbol_ids)
                if rows:
                    repo.upsert_prices(rows)
                    loaded.append(iso)
            except FetchError as exc:
                if exc.status == 404:
                    missing.append(iso)  # holiday, or not yet published
                else:
                    log.warning("bhavcopy %s failed: %s", iso, exc)
                    errors.append(f"bhavcopy {iso}: {exc}")
        if iso not in have_index:
            try:
                rows = parse_index_close(client.get(INDEX_CLOSE_URL.format(d=d)).text)
                if rows:
                    repo.upsert_index_levels(rows)
                    index_loaded.append(iso)
            except FetchError as exc:
                if exc.status != 404:
                    log.warning("index close %s failed: %s", iso, exc)
                    errors.append(f"index close {iso}: {exc}")
        if lookback > 7 and len(have_prices | set(loaded)) >= target_days:
            break  # backfill complete
    log.info("prices loaded for %s; index levels for %s; unavailable %s", loaded, index_loaded, missing)
    return {"price_days_loaded": loaded, "index_days_loaded": index_loaded, "unavailable": missing, "errors": errors}


def last_expected_trade_date() -> date:
    """Most recent weekday whose bhavcopy should be published by now (exchange holidays not known)."""
    return _candidate_dates(7)[0]

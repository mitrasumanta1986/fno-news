"""Daily fundamentals snapshot from Yahoo Finance (unofficial `yfinance`; values as the provider reports them).
NSE publishes no free per-stock fundamentals feed. Missing values stay NULL (N/A)."""
from __future__ import annotations

import logging
import math
import time

from database.repository import Repository
from technical.providers import yahoo_ticker
from utils.timeutils import now_iso

log = logging.getLogger(__name__)
SOURCE = "Yahoo Finance via yfinance (unofficial)"
FIELDS = {
    "pe": "trailingPE", "pb": "priceToBook", "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
    "market_cap": "marketCap", "earnings_growth": "earningsQuarterlyGrowth", "revenue_growth": "revenueGrowth",
    "profit_margin": "profitMargins", "dividend_yield": "dividendYield", "beta": "beta",
    "high_52w": "fiftyTwoWeekHigh", "low_52w": "fiftyTwoWeekLow",
}


def _clean(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def refresh_fundamentals(repo: Repository, pause_seconds: float = 1.0) -> dict:
    import yfinance as yf

    rows, failed = [], []
    for stock in repo.active_stocks():
        try:
            info = yf.Ticker(yahoo_ticker(stock["symbol"])).info or {}
        except Exception as exc:
            failed.append(stock["symbol"])
            log.debug("fundamentals %s failed: %s", stock["symbol"], exc)
            continue
        values = {k: _clean(info.get(src)) for k, src in FIELDS.items()}
        if any(v is not None for v in values.values()):
            rows.append({"stock_id": stock["id"], **values, "updated_at": now_iso(), "source": SOURCE})
            if len(rows) % 50 == 0:
                repo.upsert_fundamentals(rows[-50:])  # persist progress on long runs
        time.sleep(pause_seconds)
    repo.upsert_fundamentals(rows[len(rows) - len(rows) % 50:])
    log.info("fundamentals: %s updated, %s failed", len(rows), len(failed))
    return {"fundamentals_updated": len(rows), "failed": failed[:20]}

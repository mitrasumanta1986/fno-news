"""Technical screen: evaluates indicator CONDITIONS on the last closed bar.

BULLISH setup: RSI > upper AND ADX > min AND close > Supertrend AND close > EMA20 AND close > VWAP
BEARISH setup: RSI < lower AND ADX > min AND close < Supertrend AND close < EMA20 AND close < VWAP
Otherwise NONE. On the daily timeframe VWAP is not applicable and is excluded from the rule.

This is a mechanical filter, not a recommendation.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

from config.settings import load_yaml
from database.repository import Repository
from technical import indicators as ind
from utils.timeutils import IST, now_iso, now_utc, to_iso

log = logging.getLogger(__name__)
MIN_BARS = 40


def load_config() -> dict[str, Any]:
    return load_yaml("technical.yaml")


def _f(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else round(value, 4)


def evaluate(df: pd.DataFrame, cfg: dict[str, Any], use_vwap: bool) -> dict[str, Any] | None:
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < MIN_BARS:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    rsi_v = ind.rsi(c, cfg["rsi"]["period"]).iloc[-1]
    adx_v = ind.adx(h, l, c, cfg["adx"]["period"]).iloc[-1]
    st_line, _ = ind.supertrend(h, l, c, cfg["supertrend"]["period"], cfg["supertrend"]["multiplier"])
    st_v = st_line.iloc[-1]
    ema_v = ind.ema(c, cfg["ema"]["period"]).iloc[-1]
    vwap_v = ind.session_vwap(df).iloc[-1] if use_vwap else None
    close = c.iloc[-1]

    rsi_v, adx_v, st_v, ema_v, vwap_v, close = map(_f, (rsi_v, adx_v, st_v, ema_v, vwap_v, close))
    if None in (rsi_v, adx_v, st_v, ema_v, close):
        return None
    rsi_state = ("BULLISH" if rsi_v > cfg["rsi"]["bullish_above"]
                 else "BEARISH" if rsi_v < cfg["rsi"]["bearish_below"] else "NEUTRAL")
    adx_ok = adx_v > cfg["adx"]["min_trend_strength"]
    above_st, above_ema = close > st_v, close > ema_v
    above_vwap = (close > vwap_v) if (use_vwap and vwap_v is not None) else None

    price_checks_bull = [above_st, above_ema] + ([above_vwap] if use_vwap else [])
    price_checks_bear = [not above_st, not above_ema] + ([above_vwap is False] if use_vwap else [])
    if use_vwap and above_vwap is None:
        setup = "NONE"
    elif rsi_state == "BULLISH" and adx_ok and all(price_checks_bull):
        setup = "BULLISH"
    elif rsi_state == "BEARISH" and adx_ok and all(price_checks_bear):
        setup = "BEARISH"
    else:
        setup = "NONE"
    return {
        "close": close, "rsi": rsi_v, "adx": adx_v, "supertrend": st_v, "ema20": ema_v, "vwap": vwap_v,
        "rsi_state": rsi_state, "adx_ok": int(adx_ok), "above_supertrend": int(above_st),
        "above_ema20": int(above_ema), "above_vwap": None if above_vwap is None else int(above_vwap),
        "setup": setup, "bar_time": to_iso(df.index[-1].to_pydatetime()),
    }


def run_daily_screen(repo: Repository) -> dict:
    cfg = load_config()
    rows = []
    for stock in repo.active_stocks():
        records = repo.price_frame_rows(stock["id"], limit=250)
        if len(records) < MIN_BARS:
            continue
        df = pd.DataFrame([dict(r) for r in records]).iloc[::-1]
        df.index = pd.to_datetime(df.pop("trade_date")).dt.tz_localize(IST) + pd.Timedelta(hours=15, minutes=30)
        result = evaluate(df.astype(float), cfg, use_vwap=False)
        if result:
            rows.append({**result, "stock_id": stock["id"], "timeframe": "1d", "computed_at": now_iso(),
                         "data_source": "NSE bhavcopy (EOD)"})
    repo.upsert_technical_signals(rows)
    log.info("daily technical screen: %s stocks evaluated", len(rows))
    return {"daily_evaluated": len(rows)}


def run_intraday_screen(repo: Repository) -> dict:
    cfg = load_config()
    icfg = cfg.get("intraday", {})
    if icfg.get("provider", "none") != "yfinance":
        return {"intraday_evaluated": 0, "skipped": "intraday provider disabled"}
    from technical.providers import YFinanceProvider

    stocks = {s["symbol"]: s["id"] for s in repo.active_stocks()}
    provider = YFinanceProvider(interval=icfg.get("interval", "5m"), period=icfg.get("period", "5d"),
                                batch_size=int(icfg.get("batch_size", 50)))
    from functools import lru_cache

    from technical.intraday import INDEX_TICKERS, index_snapshot, rebase_prev_close, stock_snapshot

    stock_prev = lru_cache(maxsize=4)(repo.official_stock_prev_close)
    index_prev = lru_cache(maxsize=4)(repo.official_index_prev_close)
    frames = provider.fetch(list(stocks))
    avg_volume = repo.avg_daily_volume(20)
    rows, snaps = [], []
    for symbol, df in frames.items():
        stock_id = stocks[symbol]
        try:
            result = evaluate(df, cfg, use_vwap=True)
            snap = stock_snapshot(df, avg_volume.get(stock_id))
            if snap:
                rebase_prev_close(snap, stock_prev(snap["session_date"]).get(stock_id))
        except Exception:
            log.exception("intraday evaluation failed for %s", symbol)
            continue
        if result:
            rows.append({**result, "stock_id": stock_id, "timeframe": icfg.get("interval", "5m"),
                         "computed_at": now_iso(), "data_source": provider.label})
        if snap:
            snaps.append({**snap, "stock_id": stock_id, "source": provider.label})
    repo.upsert_technical_signals(rows)
    repo.upsert_intraday_snapshot(snaps)

    index_rows = []
    for name, df in provider.fetch_tickers(INDEX_TICKERS).items():
        snap = index_snapshot(name, df, provider.label)
        if snap:
            index_rows.append(rebase_prev_close(snap, index_prev(snap["session_date"]).get(name)))
    repo.upsert_intraday_index(index_rows)
    log.info("intraday: %s signals, %s snapshots, %s indices (of %s stocks)", len(rows), len(snaps), len(index_rows), len(stocks))
    return {"intraday_evaluated": len(rows), "snapshots": len(snaps), "indices": len(index_rows), "requested": len(stocks)}


def intraday_session_active() -> bool:
    now = now_utc().astimezone(IST)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 15 <= minutes <= 15 * 60 + 40

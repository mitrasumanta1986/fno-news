"""Intraday state from closed 5-minute bars: day change, VWAP, opening range, relative volume."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from technical import indicators as ind
from utils.timeutils import IST, now_iso, to_iso

SESSION_MINUTES = 375  # 09:15-15:30
ORB_MINUTES = 15

INDEX_TICKERS = {
    "^NSEI": "Nifty 50", "^NSEBANK": "Nifty Bank", "NIFTY_FIN_SERVICE.NS": "Nifty Financial Services",
    "^INDIAVIX": "India VIX", "^CNXIT": "Nifty IT", "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma",
    "^CNXMETAL": "Nifty Metal", "^NSMIDCP": "Nifty Next 50", "NIFTY_MID_SELECT.NS": "Nifty Midcap Select",
}


def _f(v: Any) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, 4)


def _sessions(df: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    local = df.tz_convert(IST) if df.index.tz is not None else df.tz_localize(IST)
    dates = sorted(set(local.index.date))
    today = local[local.index.date == dates[-1]]
    prev = local[local.index.date == dates[-2]] if len(dates) > 1 else None
    prev_close = float(prev["close"].iloc[-1]) if prev is not None and not prev.empty else None
    return today, prev_close


def stock_snapshot(df: pd.DataFrame, avg_volume_20d: float | None) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    today, prev_close = _sessions(df)
    if today.empty:
        return None
    last = float(today["close"].iloc[-1])
    start = today.index[0].replace(hour=9, minute=15)
    orb = today[today.index < start + pd.Timedelta(minutes=ORB_MINUTES)]
    orb_high = float(orb["high"].max()) if not orb.empty else None
    orb_low = float(orb["low"].min()) if not orb.empty else None
    orb_complete = today.index[-1] >= start + pd.Timedelta(minutes=ORB_MINUTES)
    orb_status = None
    if orb_complete and orb_high is not None:
        orb_status = "ABOVE_ORB" if last > orb_high else "BELOW_ORB" if last < orb_low else "INSIDE"
    day_volume = float(today["volume"].sum())
    elapsed = (today.index[-1] + pd.Timedelta(minutes=5) - start).total_seconds() / 60
    rel_vol = None
    if avg_volume_20d and elapsed > 0:
        rel_vol = day_volume / (avg_volume_20d * min(elapsed, SESSION_MINUTES) / SESSION_MINUTES)
    vwap = ind.session_vwap(today).iloc[-1]
    return {
        "session_date": today.index[-1].date().isoformat(), "bar_time": to_iso(today.index[-1].to_pydatetime()),
        "last": _f(last), "day_open": _f(today["open"].iloc[0]), "day_high": _f(today["high"].max()),
        "day_low": _f(today["low"].min()), "prev_close": _f(prev_close),
        "change_pct": _f((last - prev_close) / prev_close * 100) if prev_close else None,
        "day_volume": _f(day_volume), "avg_volume_20d": _f(avg_volume_20d), "relative_volume": _f(rel_vol),
        "vwap": _f(vwap), "orb_high": _f(orb_high), "orb_low": _f(orb_low), "orb_status": orb_status,
        "computed_at": now_iso(),
    }


def rebase_prev_close(snap: dict[str, Any], official_prev_close: float | None) -> dict[str, Any]:
    """Replace Yahoo's prior-session last bar with NSE's official close so % change matches NSE."""
    if snap and official_prev_close and snap.get("last") is not None:
        snap["prev_close"] = _f(official_prev_close)
        snap["change_pct"] = _f((snap["last"] - official_prev_close) / official_prev_close * 100)
    return snap


def index_snapshot(name: str, df: pd.DataFrame, source: str) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    today, prev_close = _sessions(df)
    if today.empty:
        return None
    last = float(today["close"].iloc[-1])
    return {
        "index_name": name, "session_date": today.index[-1].date().isoformat(),
        "bar_time": to_iso(today.index[-1].to_pydatetime()), "last": _f(last), "prev_close": _f(prev_close),
        "change_pct": _f((last - prev_close) / prev_close * 100) if prev_close else None,
        "day_high": _f(today["high"].max()), "day_low": _f(today["low"].min()), "computed_at": now_iso(),
        "source": source,
    }

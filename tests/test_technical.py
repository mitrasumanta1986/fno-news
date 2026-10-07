import numpy as np
import pandas as pd

from technical import indicators as ind
from technical.screener import evaluate, load_config


def _frame(closes, volume=1000.0, freq="5min", start="2026-09-28 09:15"):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="Asia/Kolkata")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c.shift().fillna(c.iloc[0]), "high": c + 1, "low": c - 1, "close": c, "volume": volume})


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).iloc[-1] == 100.0
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] < 1


def test_session_vwap_resets_daily():
    idx = pd.to_datetime(["2026-09-25 15:25", "2026-09-28 09:15", "2026-09-28 09:20"]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({"high": [101, 11, 13], "low": [99, 9, 11], "close": [100, 10, 12], "volume": [1, 1, 3]}, index=idx)
    vwap = ind.session_vwap(df)
    assert vwap.iloc[0] == 100 and vwap.iloc[1] == 10 and vwap.iloc[2] == (10 * 1 + 12 * 3) / 4


def test_supertrend_direction_follows_trend():
    df = _frame(np.linspace(100, 200, 80))
    _, direction = ind.supertrend(df["high"], df["low"], df["close"], 10, 3)
    assert direction.iloc[-1] == 1
    df = _frame(np.linspace(200, 100, 80))
    _, direction = ind.supertrend(df["high"], df["low"], df["close"], 10, 3)
    assert direction.iloc[-1] == -1


def test_screen_bullish_and_bearish():
    cfg = load_config()
    rng = np.random.default_rng(0)
    up = np.linspace(100, 160, 90) + rng.normal(0, 0.3, 90)
    assert evaluate(_frame(up), cfg, use_vwap=True)["setup"] == "BULLISH"
    assert evaluate(_frame(up[::-1]), cfg, use_vwap=True)["setup"] == "BEARISH"
    flat = 100 + rng.normal(0, 0.5, 90)
    assert evaluate(_frame(flat), cfg, use_vwap=True)["setup"] == "NONE"


def test_screen_needs_enough_bars():
    assert evaluate(_frame(np.linspace(100, 110, 20)), load_config(), use_vwap=True) is None


def test_daily_screen_excludes_vwap():
    result = evaluate(_frame(np.linspace(100, 160, 90), freq="D"), load_config(), use_vwap=False)
    assert result["vwap"] is None and result["above_vwap"] is None and result["setup"] == "BULLISH"

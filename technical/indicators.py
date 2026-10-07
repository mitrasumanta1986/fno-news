"""Indicator maths (pandas/numpy only). Inputs: DataFrame with open, high, low, close, volume
columns and a DatetimeIndex in ascending order. Wilder smoothing is used for RSI/ADX/ATR."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    avg_gain = _wilder(delta.clip(lower=0), period)
    avg_loss = _wilder(-delta.clip(upper=0), period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift()
    return pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return _wilder(true_range(high, low, close), period)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up, down = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    tr = _wilder(true_range(high, low, close), period)
    plus_di = 100 * _wilder(plus_dm, period) / tr
    minus_di = 100 * _wilder(minus_dm, period) / tr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return _wilder(dx, period)


def ema(close: pd.Series, period: int = 20) -> pd.Series:
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10,
               multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Returns (supertrend line, direction: +1 uptrend / -1 downtrend)."""
    atr_values = atr(high, low, close, period).to_numpy()
    hl2 = ((high + low) / 2).to_numpy()
    c = close.to_numpy()
    n = len(c)
    upper = hl2 + multiplier * atr_values
    lower = hl2 - multiplier * atr_values
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    line = np.full(n, np.nan)
    direction = np.zeros(n)
    for i in range(n):
        if np.isnan(atr_values[i]):
            continue
        if i == 0 or np.isnan(final_upper[i - 1]):
            final_upper[i], final_lower[i] = upper[i], lower[i]
            direction[i] = 1 if c[i] > upper[i] else -1
        else:
            final_upper[i] = upper[i] if (upper[i] < final_upper[i - 1] or c[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
            final_lower[i] = lower[i] if (lower[i] > final_lower[i - 1] or c[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
            if direction[i - 1] == -1 and c[i] > final_upper[i - 1]:
                direction[i] = 1
            elif direction[i - 1] == 1 and c[i] < final_lower[i - 1]:
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]
        line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
    return pd.Series(line, index=close.index), pd.Series(direction, index=close.index)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP anchored to each trading session (resets daily)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume = df["volume"].fillna(0)
    session = df.index.date
    pv = (typical * volume).groupby(session).cumsum()
    cum_vol = volume.groupby(session).cumsum().replace(0, np.nan)
    return pv / cum_vol

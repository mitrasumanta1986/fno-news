"""Per-stock multi-factor scorecard: technical, fundamental, liquidity, movement and news.

Each factor gets a DESCRIPTIVE reading (e.g. "Bullish setup", "High liquidity", "Strong up-move").
No factor is turned into a buy/sell/hold call and there is no combined verdict.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from technical import indicators as ind


def movement_metrics(prices: pd.DataFrame) -> pd.DataFrame:
    """prices: stock_id, trade_date, high, low, close, volume (all history). One row per stock."""
    out = []
    for stock_id, g in prices.sort_values("trade_date").groupby("stock_id"):
        c = g["close"].astype(float).reset_index(drop=True)
        if len(c) < 2:
            continue
        ret = lambda n: (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else np.nan  # noqa: E731
        atr = ind.atr(g["high"].astype(float).reset_index(drop=True), g["low"].astype(float).reset_index(drop=True), c, 14)
        value = (g["close"] * g["volume"]).tail(20).mean()
        out.append({
            "stock_id": stock_id, "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20), "ret_60d": ret(min(59, len(c) - 1)),
            "atr_pct": atr.iloc[-1] / c.iloc[-1] * 100 if pd.notna(atr.iloc[-1]) else np.nan,
            "off_high_pct": (c.iloc[-1] / c.max() - 1) * 100, "avg_traded_value_20d": value,
        })
    return pd.DataFrame(out)


def _tier(series: pd.Series, labels=("Low", "Medium", "High")) -> pd.Series:
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series("N/A", index=series.index)
    ranks = series.rank(pct=True)
    return pd.cut(ranks, [0, 1 / 3, 2 / 3, 1.0001], labels=list(labels), include_lowest=True).astype(object).where(series.notna(), "N/A")


def technical_reading(setup_5m, setup_1d) -> str:
    parts = []
    for tf, s in (("5m", setup_5m), ("1D", setup_1d)):
        if isinstance(s, str) and s != "NONE":
            parts.append(f"{s.title()} ({tf})")
    return " · ".join(parts) if parts else "No setup"


def movement_reading(ret_5d, ret_20d) -> str:
    if pd.isna(ret_5d) or pd.isna(ret_20d):
        return "N/A"
    if ret_5d > 3 and ret_20d > 5:
        return "Strong up-move"
    if ret_5d < -3 and ret_20d < -5:
        return "Strong down-move"
    if ret_20d > 0:
        return "Mild up-trend"
    return "Mild down-trend"


def fundamental_reading(pe, roe, earnings_growth) -> str:
    bits = []
    if pd.notna(roe):
        bits.append("High ROE" if roe >= 0.18 else "Low ROE" if roe < 0.08 else "Moderate ROE")
    if pd.notna(earnings_growth):
        bits.append("Earnings growing" if earnings_growth > 0.1 else "Earnings falling" if earnings_growth < 0 else "Earnings flat")
    if pd.notna(pe):
        bits.append("Loss/neg. P/E" if pe <= 0 else f"P/E {pe:.0f}")
    return " · ".join(bits) if bits else "N/A"


def _count(v) -> int:
    return 0 if v is None or pd.isna(v) else int(v)


def news_reading(news_7d, pos, neg) -> str:
    news_7d, pos, neg = _count(news_7d), _count(pos), _count(neg)
    if news_7d == 0 and pos + neg == 0:
        return "Quiet"
    parts = [f"{news_7d} articles (7d)"]
    if pos or neg:
        parts.append(f"published ratings: {pos} positive / {neg} negative")
    return " · ".join(parts)


def build_scorecard(stocks: pd.DataFrame, movement: pd.DataFrame, fundamentals: pd.DataFrame, fo: pd.DataFrame,
                    tech: pd.DataFrame, news_counts: pd.DataFrame, rec_counts: pd.DataFrame) -> pd.DataFrame:
    df = stocks.rename(columns={"id": "stock_id"})
    for other in (movement, fundamentals, fo, tech, news_counts, rec_counts):
        if not other.empty:
            df = df.merge(other, on="stock_id", how="left")
    for col in ("ret_1d", "ret_5d", "ret_20d", "ret_60d", "atr_pct", "off_high_pct", "avg_traded_value_20d", "pe", "pb",
                "roe", "debt_to_equity", "market_cap", "earnings_growth", "total_contracts", "turnover", "oi_contracts",
                "setup_5m", "setup_1d", "rsi_1d", "adx_1d", "news_7d", "pos_recs", "neg_recs"):
        if col not in df:
            df[col] = np.nan
    df["liquidity_score"] = df[["turnover", "avg_traded_value_20d"]].rank(pct=True).mean(axis=1)
    df["Liquidity"] = _tier(df["liquidity_score"])
    df["Volatility"] = _tier(df["atr_pct"], ("Low", "Medium", "High"))
    df["Technical"] = [technical_reading(a, b) for a, b in zip(df["setup_5m"], df["setup_1d"])]
    df["Movement"] = [movement_reading(a, b) for a, b in zip(df["ret_5d"], df["ret_20d"])]
    df["Fundamental"] = [fundamental_reading(p, r, e) for p, r, e in zip(df["pe"], df["roe"], df["earnings_growth"])]
    df["News"] = [news_reading(n, p, q) for n, p, q in zip(df["news_7d"], df["pos_recs"], df["neg_recs"])]
    return df

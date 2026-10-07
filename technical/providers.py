"""Intraday bar provider.

NSE does not publish free intraday candles. Yahoo Finance (via the unofficial `yfinance`
library) is used for delayed 5-minute bars; its data is for personal use and may be delayed,
incomplete or unavailable. Only closed bars are returned.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from utils.timeutils import now_utc

log = logging.getLogger(__name__)

_INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


def yahoo_ticker(symbol: str) -> str:
    return f"{symbol}.NS"


class YFinanceProvider:
    label = "Yahoo Finance via yfinance (unofficial, delayed)"

    def __init__(self, interval: str = "5m", period: str = "5d", batch_size: int = 50, pause_seconds: float = 2.0):
        self.interval = interval
        self.period = period
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds

    def fetch(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """NSE symbols -> closed bars."""
        return self.fetch_tickers({yahoo_ticker(s): s for s in symbols})

    def fetch_tickers(self, ticker_map: dict[str, str]) -> dict[str, pd.DataFrame]:
        """Yahoo ticker -> our key. Returns key -> closed bars (open/high/low/close/volume)."""
        import yfinance as yf  # optional dependency

        out: dict[str, pd.DataFrame] = {}
        bar = pd.Timedelta(minutes=_INTERVAL_MINUTES.get(self.interval, 5))
        now = pd.Timestamp(now_utc())
        items = list(ticker_map.items())
        for i in range(0, len(items), self.batch_size):
            tickers = dict(items[i:i + self.batch_size])
            try:
                data = yf.download(list(tickers), period=self.period, interval=self.interval, group_by="ticker",
                                   auto_adjust=False, progress=False, threads=False)
            except Exception as exc:  # provider failures must not break the worker
                log.warning("yfinance batch %s failed: %s", i // self.batch_size, exc)
                continue
            for ticker, symbol in tickers.items():
                try:
                    df = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
                except KeyError:
                    continue
                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
                df = df[df.index + bar <= now]  # drop the still-forming bar
                if not df.empty:
                    out[symbol] = df.astype(float)
            time.sleep(self.pause_seconds)
        return out

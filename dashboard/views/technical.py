from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from technical.screener import load_config


def render() -> None:
    cfg = load_config()
    st.title("Technical Screen")
    st.warning(
        "Mechanical indicator **conditions**, not recommendations. "
        f"**Bullish setup**: RSI > {cfg['rsi']['bullish_above']}, ADX > {cfg['adx']['min_trend_strength']}, price above "
        f"Supertrend({cfg['supertrend']['period']},{cfg['supertrend']['multiplier']}), EMA{cfg['ema']['period']} and VWAP. "
        f"**Bearish setup**: RSI < {cfg['rsi']['bearish_below']}, ADX > {cfg['adx']['min_trend_strength']}, price below all three."
    )
    _screen(cfg)


@st.fragment(run_every="60s")
def _screen(cfg: dict) -> None:
    intraday_tf = cfg.get("intraday", {}).get("interval", "5m")
    tf = st.radio("Timeframe", [intraday_tf, "1d"], horizontal=True,
                  format_func=lambda t: f"{t} intraday (Yahoo Finance via yfinance — unofficial, delayed)" if t != "1d"
                  else "Daily (NSE EOD bhavcopy; VWAP not applicable)")
    q.technical_signals.clear()
    df = q.technical_signals(tf)
    if df.empty:
        st.info("No signals yet. Intraday runs every few minutes during market hours via the worker "
                "(`python worker.py --once --job technical` to run now). Daily runs with the EOD price job.")
        return
    st.caption(f"Last closed bar: {fmt.ist(df['bar_time'].max())} · computed {fmt.ist(df['computed_at'].max())} · "
               f"source: {df['data_source'].iloc[0]} · {len(df)} stocks evaluated · page auto-refreshes every 60 s"
               + (" · Yahoo bars lag ~10-15 min and its NSE data ends at 15:15 IST" if tf != "1d" else ""))

    def table(frame: pd.DataFrame) -> pd.DataFrame:
        yes = lambda v: "N/A" if pd.isna(v) else ("✔" if v else "✘")  # noqa: E731
        return pd.DataFrame({
            "Symbol": frame["symbol"], "Stock": frame["name"], "Close": frame["close"], "RSI": frame["rsi"],
            "ADX": frame["adx"], "Supertrend": frame["supertrend"], "EMA20": frame["ema20"], "VWAP": frame["vwap"],
            "RSI state": frame["rsi_state"], "ADX>min": frame["adx_ok"].map(yes),
            "Above ST": frame["above_supertrend"].map(yes), "Above EMA20": frame["above_ema20"].map(yes),
            "Above VWAP": frame["above_vwap"].map(yes),
        })

    cols = {c: st.column_config.NumberColumn(format="%.2f") for c in ("Close", "RSI", "ADX", "Supertrend", "EMA20", "VWAP")}
    bull = df[df["setup"] == "BULLISH"].sort_values("adx", ascending=False)
    bear = df[df["setup"] == "BEARISH"].sort_values("adx", ascending=False)
    t1, t2, t3 = st.tabs([f"Bullish setups ({len(bull)})", f"Bearish setups ({len(bear)})", f"All stocks ({len(df)})"])
    for tab, frame, key in ((t1, bull, "bull"), (t2, bear, "bear"), (t3, df.sort_values("symbol"), "all")):
        with tab:
            if frame.empty:
                st.info("No stock currently meets every condition.")
                continue
            shown = table(frame).reset_index(drop=True)
            event = st.dataframe(shown, hide_index=True, width="stretch", column_config=cols, key=f"tech_{key}",
                                 on_select="rerun", selection_mode="single-row")
            rows = event.selection.rows if event else []
            if rows and st.button(f"Open {shown.iloc[rows[0]]['Symbol']} detail →", key=f"open_tech_{key}"):
                ui.open_stock(shown.iloc[rows[0]]["Symbol"])

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from dashboard import style
from technical.screener import intraday_session_active


def render() -> None:
    st.title("Intraday F&O")
    style.banner("Live-ish intraday view of F&O stocks from closed 5-minute bars (Yahoo Finance via yfinance — unofficial, "
                 "delayed). Shows conditions such as VWAP position, opening-range breaks and volume surges. These are not "
                 "trade calls; no orders are ever placed.")
    _live()


@st.fragment(run_every="60s")
def _live() -> None:
    q.intraday_snapshot.clear()
    q.live_index_levels.clear()
    q.technical_signals.clear()
    snap = q.intraday_snapshot()
    state = "🟢 Market session active" if intraday_session_active() else "⚪ Outside market hours — showing last session"
    st.caption(f"{state} · auto-refreshes every 60 s · worker updates bars every 5 min")
    ui.live_index_tiles()
    if snap.empty:
        st.info("No intraday data yet — the worker fills this during market hours (`python worker.py --once --job technical`).")
        return
    st.caption(f"F&O stocks — last closed 5-min bar: {fmt.ist(snap['bar_time'].max())}")

    adv, dec = int((snap["change_pct"] > 0).sum()), int((snap["change_pct"] < 0).sum())
    above_vwap = int((snap["last"] > snap["vwap"]).sum())
    style.ratio_bar([("▲ Adv", adv, style.GREEN), ("▼ Dec", dec, style.RED)])
    m = st.columns(4)
    m[0].metric("Advancing / Declining", f"{adv} / {dec}")
    m[1].metric("Above VWAP", f"{above_vwap} / {len(snap)}")
    m[2].metric("Above ORB high", int((snap["orb_status"] == "ABOVE_ORB").sum()))
    m[3].metric("Below ORB low", int((snap["orb_status"] == "BELOW_ORB").sum()))

    tech = q.technical_signals("5m")[["stock_id", "setup", "rsi", "adx"]]
    df = snap.merge(tech, on="stock_id", how="left")
    df["VWAP position"] = ["Above VWAP" if pd.notna(v) and l > v else "Below VWAP" if pd.notna(v) else "N/A"
                           for l, v in zip(df["last"], df["vwap"])]
    df["ORB"] = df["orb_status"].map({"ABOVE_ORB": "Above ORB high", "BELOW_ORB": "Below ORB low", "INSIDE": "Inside ORB"}).fillna("N/A")
    df["5m setup"] = df["setup"].map({"BULLISH": "Bullish setup", "BEARISH": "Bearish setup", "NONE": "No setup"}).fillna("N/A")

    def table(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({
            "Symbol": frame["symbol"], "Stock": frame["name"], "Last ₹": frame["last"], "Chg %": frame["change_pct"],
            "Day high": frame["day_high"], "Day low": frame["day_low"], "VWAP": frame["vwap"],
            "VWAP position": frame["VWAP position"], "ORB": frame["ORB"], "Rel. volume": frame["relative_volume"],
            "RSI 5m": frame["rsi"], "ADX 5m": frame["adx"], "5m setup": frame["5m setup"],
        }).reset_index(drop=True)

    fmts = {"Last ₹": "{:,.2f}", "Chg %": "{:+.2f}", "Day high": "{:,.2f}", "Day low": "{:,.2f}", "VWAP": "{:,.2f}",
            "Rel. volume": "{:.2f}x", "RSI 5m": "{:.1f}", "ADX 5m": "{:.1f}"}
    views = {
        "🚀 Top gainers": df.nlargest(15, "change_pct"),
        "📉 Top losers": df.nsmallest(15, "change_pct"),
        "🔊 Volume surge (≥2x)": df[df["relative_volume"] >= 2].sort_values("relative_volume", ascending=False),
        "⬆️ Above ORB high": df[df["orb_status"] == "ABOVE_ORB"].sort_values("change_pct", ascending=False),
        "⬇️ Below ORB low": df[df["orb_status"] == "BELOW_ORB"].sort_values("change_pct"),
        "🟢 Bullish 5m setups": df[df["setup"] == "BULLISH"].sort_values("adx", ascending=False),
        "🔴 Bearish 5m setups": df[df["setup"] == "BEARISH"].sort_values("adx", ascending=False),
        "📋 All": df.sort_values("symbol"),
    }
    tabs = st.tabs([f"{k} ({len(v)})" for k, v in views.items()])
    for tab, (name, frame) in zip(tabs, views.items()):
        with tab:
            if frame.empty:
                st.info("Nothing matches right now.")
                continue
            t = table(frame)
            event = st.dataframe(style.styled(t, change_cols=["Chg %"], word_cols=["VWAP position", "ORB", "5m setup"], formats=fmts),
                                 hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                                 key=f"intra_{name}")
            if event and event.selection.rows and st.button("Open detail →", key=f"open_{name}"):
                ui.open_stock(t.iloc[event.selection.rows[0]]["Symbol"])
    st.caption("Rel. volume = today's volume ÷ (20-day average daily volume × fraction of session elapsed). "
               "ORB = high/low of the first 15 minutes. F&O open interest is published by NSE end-of-day only.")

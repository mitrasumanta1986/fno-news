from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from dashboard import style

FACTORS = ["Technical", "Fundamental", "Liquidity", "Movement", "News"]


def _num(v, pattern="{:,.2f}", scale=1.0) -> str:
    return "N/A" if v is None or pd.isna(v) else pattern.format(v * scale)


def render() -> None:
    st.title("F&O Stock Analysis")
    style.banner("Five-factor scorecard for every F&O stock — technical, fundamental, liquidity, movement and news. "
                 "Each factor shows a descriptive reading; there is deliberately no combined buy/sell verdict.")
    df = q.scorecard_frame()
    if df.empty:
        st.info("No data yet.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    sectors = c1.multiselect("Sector", sorted(df["sector"].dropna().unique()))
    tech = c2.selectbox("Technical", ["Any", "Any bullish setup", "Any bearish setup", "No setup"])
    liq = c3.multiselect("Liquidity", ["High", "Medium", "Low"])
    move = c4.multiselect("Movement", ["Strong up-move", "Mild up-trend", "Mild down-trend", "Strong down-move"])
    news_only = c5.toggle("With published ratings (30d)")

    view = df
    if sectors:
        view = view[view["sector"].isin(sectors)]
    if tech == "Any bullish setup":
        view = view[view["Technical"].str.contains("Bullish")]
    elif tech == "Any bearish setup":
        view = view[view["Technical"].str.contains("Bearish")]
    elif tech == "No setup":
        view = view[view["Technical"] == "No setup"]
    if liq:
        view = view[view["Liquidity"].isin(liq)]
    if move:
        view = view[view["Movement"].isin(move)]
    if news_only:
        view = view[(view["pos_recs"].fillna(0) + view["neg_recs"].fillna(0) + view["neutral_recs"].fillna(0)) > 0]

    table = pd.DataFrame({
        "Symbol": view["symbol"], "Stock": view["name"], "Sector": view["sector"].map(fmt.na),
        "Technical": view["Technical"], "Fundamental": view["Fundamental"], "Liquidity": view["Liquidity"],
        "Movement": view["Movement"], "News": view["News"],
        "1D %": view["ret_1d"], "5D %": view["ret_5d"], "20D %": view["ret_20d"], "RSI (1D)": view["rsi_1d"],
        "ADX (1D)": view["adx_1d"], "P/E": view["pe"], "ROE %": view["roe"] * 100, "F&O ₹ cr": view["turnover"] / 1e7,
        "Volatility": view["Volatility"],
    }).sort_values("Symbol").reset_index(drop=True)
    st.caption(f"{len(table)} of {len(df)} stocks · Prices/F&O: NSE EOD · Intraday setups & fundamentals: Yahoo Finance via "
               "yfinance (unofficial) · select a row for the factor breakdown")
    event = st.dataframe(
        style.styled(table, change_cols=["1D %", "5D %", "20D %"],
                     word_cols=["Technical", "Fundamental", "Liquidity", "Movement", "Volatility"],
                     formats={"1D %": "{:+.2f}", "5D %": "{:+.2f}", "20D %": "{:+.2f}", "RSI (1D)": "{:.1f}",
                              "ADX (1D)": "{:.1f}", "P/E": "{:.1f}", "ROE %": "{:.1f}", "F&O ₹ cr": "{:,.0f}"}),
        hide_index=True, width="stretch", height=560, on_select="rerun", selection_mode="single-row")
    rows = event.selection.rows if event else []
    if not rows:
        return
    symbol = table.iloc[rows[0]]["Symbol"]
    r = df[df["symbol"] == symbol].iloc[0]
    st.subheader(f"{r['name']} ({symbol}) — factor breakdown")
    cards = [
        ("📐 Technical", style.BLUE,
         f"{r['Technical']}<br>RSI 1D {_num(r['rsi_1d'], '{:.1f}')} · ADX 1D {_num(r['adx_1d'], '{:.1f}')} · "
         f"RSI 5m {_num(r.get('rsi_5m'), '{:.1f}')}"),
        ("🏛️ Fundamental", style.VIOLET,
         f"P/E {_num(r['pe'], '{:.1f}')} · P/B {_num(r['pb'], '{:.2f}')} · ROE {_num(r['roe'], '{:.1f}%', 100)}<br>"
         f"Debt/Equity {_num(r['debt_to_equity'], '{:.1f}')} · Earnings growth {_num(r['earnings_growth'], '{:+.1f}%', 100)} · "
         f"Mkt cap {_num(r['market_cap'], '₹{:,.0f} cr', 1e-7)}"),
        ("💧 Liquidity", style.GREEN if r["Liquidity"] == "High" else style.AMBER,
         f"{r['Liquidity']} · F&O contracts {_num(r['total_contracts'], '{:,.0f}')} · F&O turnover "
         f"{_num(r['turnover'], '₹{:,.0f} cr', 1e-7)}<br>OI {_num(r['oi_contracts'], '{:,.0f}')} contracts · "
         f"Cash traded value (20D avg) {_num(r['avg_traded_value_20d'], '₹{:,.0f} cr', 1e-7)}"),
        ("🏃 Movement", style.tone_for(r["ret_20d"]),
         f"{r['Movement']}<br>1D {_num(r['ret_1d'], '{:+.2f}%')} · 5D {_num(r['ret_5d'], '{:+.2f}%')} · "
         f"20D {_num(r['ret_20d'], '{:+.2f}%')} · ATR {_num(r['atr_pct'], '{:.2f}%')} · "
         f"{_num(r['off_high_pct'], '{:+.1f}%')} vs 60D high"),
        ("📰 News", style.AMBER,
         f"{r['News']}<br>Neutral/Hold ratings (30d): {int(r['neutral_recs']) if pd.notna(r['neutral_recs']) else 0}"),
    ]
    cols = st.columns(len(cards))
    for col, (title, color, body) in zip(cols, cards):
        col.markdown(style.card(title, body, color), unsafe_allow_html=True)
    st.caption("Readings are descriptive thresholds (e.g. ROE ≥ 18% = High ROE; 5-day > +3% and 20-day > +5% = Strong "
               "up-move; liquidity tiers are terciles across the F&O universe). They are not recommendations.")
    if st.button(f"Open {symbol} detail →", type="primary"):
        ui.open_stock(symbol)

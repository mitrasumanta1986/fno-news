from __future__ import annotations

import streamlit as st

from dashboard import charts
from dashboard import components as ui
from dashboard import queries as q


def render() -> None:
    st.title("F&O Activity — Top 10")
    df = q.fo_activity_latest()
    if df.empty:
        st.info("F&O bhavcopy not loaded yet — run `python worker.py --once --job prices`.")
        return
    st.caption(f"Stock futures + stock options combined, from the official NSE F&O bhavcopy for "
               f"**{df['trade_date'].iloc[0]}** (end of day). Index derivatives are excluded.")
    df = df.assign(turnover_cr=df["turnover"] / 1e7)

    specs = [
        ("Highest open interest", "oi_contracts", "Open interest (contracts)", ",.0f"),
        ("Highest volume", "total_contracts", "Contracts traded", ",.0f"),
        ("Highest traded value", "turnover_cr", "Notional turnover (₹ cr)", ",.2f"),
    ]
    tabs = st.tabs([s[0] for s in specs])
    for tab, (title, col, label, number_format) in zip(tabs, specs):
        with tab:
            top = df.nlargest(10, col)
            left, right = st.columns([3, 2])
            left.altair_chart(charts.top_bars(top[["symbol", "name", col]], col, label, number_format), width="stretch")
            table = top[["symbol", "name", "sector", "oi_contracts", "oi_change", "fut_contracts", "opt_contracts",
                         "turnover_cr", "underlying_price"]].rename(columns={
                "symbol": "Symbol", "name": "Stock", "sector": "Sector", "oi_contracts": "OI (contracts)",
                "oi_change": "OI chg (shares)", "fut_contracts": "Fut contracts", "opt_contracts": "Opt contracts",
                "turnover_cr": "Turnover ₹ cr", "underlying_price": "Underlying ₹"})
            event = right.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                                    selection_mode="single-row", key=f"fo_{col}",
                                    column_config={c: st.column_config.NumberColumn(format="localized") for c in
                                                   ("OI (contracts)", "OI chg (shares)", "Fut contracts", "Opt contracts",
                                                    "Turnover ₹ cr", "Underlying ₹")})
            rows = event.selection.rows if event else []
            if rows and right.button(f"Open {table.iloc[rows[0]]['Symbol']} detail →", key=f"open_{col}"):
                ui.open_stock(table.iloc[rows[0]]["Symbol"])
    st.caption("Notional turnover is NSE's reported traded value (for options this includes strike value, not just premium).")

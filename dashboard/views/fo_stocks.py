from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q


def render() -> None:
    st.title("All F&O Stocks")
    df = q.fo_stocks_table()
    if df.empty:
        st.info("F&O universe not loaded yet — run `python worker.py --once --job universe`.")
        return

    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    term = c1.text_input("Search name / symbol", placeholder="e.g. HDFC, TATASTEEL")
    sectors = c2.multiselect("Sector", sorted(df["sector"].dropna().unique()))
    actions = c3.multiselect("Latest published rating", ["BUY", "ACCUMULATE", "HOLD", "NEUTRAL", "REDUCE", "SELL", "UNMAPPED"])
    only_recs = c4.toggle("Only with ratings")

    view = df
    if term:
        t = term.lower()
        view = view[view["name"].str.lower().str.contains(t, regex=False) | view["symbol"].str.lower().str.contains(t, regex=False)]
    if sectors:
        view = view[view["sector"].isin(sectors)]
    if actions:
        view = view[view["normalized_action"].isin(actions)]
    if only_recs:
        view = view[view["normalized_action"].notna()]

    table = pd.DataFrame({
        "Stock Name": view["name"],
        "NSE Symbol": view["symbol"],
        "Sector": view["sector"].map(fmt.na),
        "Current Price": view["close"],
        "Chg %": [(c - p) / p * 100 if pd.notna(c) and pd.notna(p) and p else None for c, p in zip(view["close"], view["prev_close"])],
        "F&O Status": ["Active" if a else "Exited" for a in view["is_fo_active"]],
        "Lot": view["fo_lot_size"],
        "Latest News": view["latest_news"].map(fmt.na),
        "News link": view["latest_news_url"].map(fmt.safe_url),
        "Latest Recommendation": [fmt.action_label(n, o) for n, o in zip(view["normalized_action"], view["original_action"])],
        "Brokerage": view["brokerage"].map(fmt.na),
        "Analyst": view["analyst"].map(fmt.na),
        "Target Price": view["target_price"].map(fmt.price),
        "Stop Loss": view["stop_loss"].map(fmt.price),
        "Time Horizon": view["time_horizon_original"].map(fmt.na),
        "Recommendation Date": view["rec_date"].map(lambda v: fmt.ist(v, False)),
        "Source": view["source_name"].map(fmt.na),
        "Source link": view["article_url"].map(fmt.safe_url),
    })
    price_date = view["price_date"].dropna().max()
    st.caption(f"{len(table)} of {len(df)} F&O stocks · Current Price = NSE EOD close"
               f"{' as of ' + price_date if isinstance(price_date, str) else ''} · ratings are third-party publications · "
               "select a row to open its detail page")
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=620, on_select="rerun", selection_mode="single-row",
        column_config={
            "Current Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
            "News link": ui.LINK(display_text="Open ↗"),
            "Source link": ui.LINK(display_text="Open ↗"),
            "Latest News": st.column_config.TextColumn(width="large"),
        },
    )
    rows = event.selection.rows if event else []
    if rows:
        symbol = table.iloc[rows[0]]["NSE Symbol"]
        if st.button(f"Open {symbol} detail →", type="primary"):
            ui.open_stock(symbol)

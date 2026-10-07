from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q


def render() -> None:
    st.title("Search")
    term = st.text_input("Stock name, NSE symbol, brokerage, analyst, sector or keyword",
                         placeholder="e.g. Motilal, INFY, Pharma, order win")
    if len(term.strip()) < 2:
        st.caption("Type at least 2 characters.")
        return
    res = q.search_all(term.strip())
    t1, t2, t3 = st.tabs([f"Stocks ({len(res['stocks'])})", f"Recommendations ({len(res['recs'])})",
                          f"News ({len(res['news'])})"])
    with t1:
        stocks = res["stocks"]
        if stocks.empty:
            st.info("No matching F&O stocks.")
        else:
            event = st.dataframe(stocks, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row")
            if event and event.selection.rows and st.button("Open detail →"):
                ui.open_stock(stocks.iloc[event.selection.rows[0]]["symbol"])
    with t2:
        ui.rec_table(res["recs"].reset_index(drop=True), key="search_recs", selectable=False)
    with t3:
        news = res["news"]
        if news.empty:
            st.info("No matching news.")
        else:
            st.dataframe(pd.DataFrame({
                "Headline": news["headline"], "Stocks": news["symbols"].map(fmt.na), "Publisher": news["publisher"],
                "Category": news["category"], "Time": news["sort_ts"].map(fmt.ist), "Link": news["url"].map(fmt.safe_url),
            }), hide_index=True, width="stretch", column_config={"Link": ui.LINK(display_text="Open ↗")})

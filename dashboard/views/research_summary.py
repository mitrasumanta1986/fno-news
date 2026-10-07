from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import queries as q

COLUMNS = ["BUY", "SELL", "HOLD", "ACCUMULATE", "REDUCE", "NEUTRAL"]


def render() -> None:
    st.title("Published Research Summary")
    st.caption("Counts of ratings **published by third parties** per stock. This is a tally of publications, "
               "not a consensus or a recommendation by this dashboard. Select a stock to see every underlying article.")
    c1, c2 = st.columns([1, 3])
    days = c1.number_input("Look-back (days)", 1, 3650, 90)
    latest_only = c2.toggle("Count only the latest call per brokerage/analyst", value=True,
                            help="Avoids counting a brokerage that reiterated the same view several times more than once.")

    recs = q.recommendations(days=int(days))
    if recs.empty:
        st.info("No published recommendations in this window.")
        return
    counted = recs
    if latest_only:
        who = counted["brokerage"].fillna("") + "|" + counted["analyst"].fillna("")
        attributed = counted[who != "|"].assign(_who=who[who != "|"])
        attributed = attributed.sort_values("published_at").drop_duplicates(["symbol", "_who"], keep="last")
        counted = pd.concat([attributed.drop(columns="_who"), counted[who == "|"]])

    pivot = (counted.pivot_table(index=["symbol", "stock"], columns="normalized_action", values="id", aggfunc="count", fill_value=0)
             .reindex(columns=COLUMNS + ["UNMAPPED"], fill_value=0).reset_index())
    pivot["Total"] = pivot[COLUMNS + ["UNMAPPED"]].sum(axis=1)
    last = counted.groupby("symbol")["published_at"].max()
    pivot["Latest publication"] = pivot["symbol"].map(last).str[:10]
    pivot = pivot.sort_values(["Total", "symbol"], ascending=[False, True]).reset_index(drop=True)
    pivot = pivot.rename(columns={"symbol": "Symbol", "stock": "Stock", "UNMAPPED": "Other wording"})

    event = st.dataframe(pivot, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         column_config={"Other wording": st.column_config.NumberColumn(
                             help="Ratings whose wording has no mapping in config/normalization.yaml")})
    rows = event.selection.rows if event else []
    if rows:
        symbol = pivot.iloc[rows[0]]["Symbol"]
        st.subheader(f"Underlying publications — {symbol}")
        subset = counted[counted["symbol"] == symbol].sort_values("published_at", ascending=False).reset_index(drop=True)
        ui.rec_table(subset, key="summary_detail", selectable=False)
        ui.rec_evidence(subset, list(range(len(subset))), q.recommendation_mentions(tuple(int(i) for i in subset["id"])))

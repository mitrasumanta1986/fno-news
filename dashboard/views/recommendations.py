from __future__ import annotations

from contextlib import closing

import streamlit as st

from dashboard import components as ui
from dashboard import queries as q
from database.connection import connect
from database.repository import Repository


def render() -> None:
    st.title("Brokerage Recommendations")
    st.caption("SOURCE RECOMMENDATIONS — ratings exactly as published by the named brokerage/analyst, with the "
               "original wording kept. The same call reported by several outlets is counted once.")
    df_all = q.recommendations(days=3650, include_flagged=True)
    c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 1])
    days = c1.number_input("Days", 1, 3650, 30)
    actions = c2.multiselect("Published rating", ["BUY", "ACCUMULATE", "HOLD", "NEUTRAL", "REDUCE", "SELL", "UNMAPPED"])
    brokerages = c3.multiselect("Brokerage", sorted(df_all["brokerage"].dropna().unique()))
    symbols = c4.multiselect("Symbol", sorted(df_all["symbol"].unique()))
    show_flagged = c5.toggle("Show flagged")

    df = q.recommendations(days=int(days), include_flagged=show_flagged)
    if actions:
        df = df[df["normalized_action"].isin(actions)]
    if brokerages:
        df = df[df["brokerage"].isin(brokerages)]
    if symbols:
        df = df[df["symbol"].isin(symbols)]
    df = df.reset_index(drop=True)

    event = ui.rec_table(df, key="recs_table")
    rows = event.selection.rows if event else []
    if rows:
        st.subheader("Selected — evidence and every article that reported it")
        ui.rec_evidence(df, rows, q.recommendation_mentions(tuple(int(i) for i in df.iloc[rows]["id"])))
        b1, b2, b3 = st.columns([1, 1, 4])
        ids = [int(i) for i in df.iloc[rows]["id"]]
        if b1.button("Flag as incorrect", help="Hides the row (kept in the database, visible with 'Show flagged')"):
            _flag(ids, True)
        if b2.button("Unflag"):
            _flag(ids, False)
        if len(rows) == 1 and b3.button(f"Open {df.iloc[rows[0]]['symbol']} detail →"):
            ui.open_stock(df.iloc[rows[0]]["symbol"])


def _flag(ids: list[int], flagged: bool) -> None:
    with closing(connect()) as conn:
        Repository(conn).set_recommendations_flag(ids, flagged)
    q.clear_caches()
    st.rerun()

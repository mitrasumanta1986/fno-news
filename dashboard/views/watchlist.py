from __future__ import annotations

from contextlib import closing

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from database.connection import connect
from database.repository import Repository


def _repo_action(fn) -> None:
    with closing(connect()) as conn:
        fn(Repository(conn))
    q.clear_caches()
    st.rerun()


def render() -> None:
    st.title("Watchlist")
    stocks = q.stock_list()
    wl = q.watchlist()
    c1, c2 = st.columns([4, 1])
    labels = {r.symbol: f"{r.symbol} — {r.name}" for r in stocks.itertuples()}
    to_add = c1.multiselect("Add F&O stocks", [s for s in stocks["symbol"] if s not in set(wl["symbol"])],
                            format_func=labels.get)
    if c2.button("Add", disabled=not to_add):
        ids = stocks.set_index("symbol").loc[to_add, "id"].tolist()
        _repo_action(lambda r: [r.watchlist_add(int(i)) for i in ids])

    if wl.empty:
        st.info("Your watchlist is empty. It is stored locally in the SQLite database.")
        return

    table = pd.DataFrame({
        "Symbol": wl["symbol"], "Stock": wl["name"], "Sector": wl["sector"].map(fmt.na), "Close": wl["close"],
        "Chg %": [(c - p) / p * 100 if pd.notna(c) and pd.notna(p) and p else None for c, p in zip(wl["close"], wl["prev_close"])],
        "New news": wl["new_news"], "New recommendations": wl["new_recs"],
        "Last viewed": wl["last_viewed_at"].map(fmt.ist),
    })
    event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                         column_config={"Close": st.column_config.NumberColumn(format="₹%.2f"),
                                        "Chg %": st.column_config.NumberColumn(format="%+.2f%%")})
    rows = event.selection.rows if event else []
    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button("Mark all as seen"):
        _repo_action(lambda r: r.watchlist_mark_seen())
    if rows and b2.button("Remove selected"):
        ids = wl.iloc[rows]["stock_id"].tolist()
        _repo_action(lambda r: [r.watchlist_remove(int(i)) for i in ids])
    if len(rows) == 1 and b3.button(f"Open {wl.iloc[rows[0]]['symbol']} detail →"):
        ui.open_stock(wl.iloc[rows[0]]["symbol"])

    st.subheader("New since last visit")
    any_new = False
    for r in wl.itertuples():
        if not (r.new_news or r.new_recs):
            continue
        any_new = True
        with st.expander(f"{r.symbol} — {r.new_recs} new recommendation(s), {r.new_news} new article(s)"):
            recs = q.recommendations(days=3650, symbol=r.symbol)
            recs = recs[recs["retrieved_at"] > r.last_viewed_at].reset_index(drop=True)
            if not recs.empty:
                ui.rec_table(recs, key=f"wl_recs_{r.symbol}", selectable=False)
            news = q.news(days=3650, symbol=r.symbol, limit=100)
            ui.news_list(news.head(int(r.new_news)), collapse_clusters=False)
            if st.button("Mark as seen", key=f"seen_{r.symbol}"):
                _repo_action(lambda repo, sid=int(r.stock_id): repo.watchlist_mark_seen(sid))
    if not any_new:
        st.caption("Nothing new since you last marked the watchlist as seen.")

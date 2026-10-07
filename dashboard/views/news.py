from __future__ import annotations

import streamlit as st

from dashboard import components as ui
from dashboard import queries as q
from processing.classifier import CATEGORIES


def render() -> None:
    st.title("Latest News")
    stocks = q.stock_list()
    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
    cats = c1.multiselect("Categories", CATEGORIES)
    symbol = c2.selectbox("Stock", ["All"] + stocks["symbol"].tolist())
    keyword = c3.text_input("Keyword")
    days = c4.number_input("Days", 1, 365, 3)
    collapse = st.toggle("Collapse the same story from multiple outlets", value=True)
    df = q.news(days=int(days), categories=tuple(cats), symbol=None if symbol == "All" else symbol,
                keyword=keyword or None, limit=1000)
    st.caption(f"{len(df)} articles · headline + publisher snippet only; open the link for the full article")
    ui.news_list(df, collapse_clusters=collapse, limit=200)

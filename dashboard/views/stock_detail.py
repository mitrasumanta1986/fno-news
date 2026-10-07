from __future__ import annotations

from contextlib import closing

import pandas as pd
import streamlit as st

from config.settings import get_settings
from dashboard import charts
from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from database.connection import connect
from database.repository import Repository


def render() -> None:
    stocks = q.stock_list()
    if stocks.empty:
        st.info("F&O universe not loaded yet.")
        return
    symbols = stocks["symbol"].tolist()
    default = st.session_state.get("detail_symbol")
    index = symbols.index(default) if default in symbols else 0
    labels = {r.symbol: f"{r.symbol} — {r.name}" for r in stocks.itertuples()}
    symbol = st.selectbox("Stock", symbols, index=index, format_func=labels.get)
    st.session_state["detail_symbol"] = symbol

    d = q.stock_detail(symbol)
    info = d["info"].iloc[0]
    prices = d["prices"]
    st.title(f"{info['name']} ({symbol})")

    last = prices.iloc[-1] if not prices.empty else None
    m = st.columns(5)
    if last is not None:
        chg = (last["close"] - last["prev_close"]) / last["prev_close"] * 100 if last["prev_close"] else None
        m[0].metric(f"Close ({last['trade_date']}, NSE EOD)", fmt.price(last["close"]), fmt.pct(chg) if chg is not None else None)
    else:
        m[0].metric("Close", "N/A")
    m[1].metric("F&O status", "Active" if info["is_fo_active"] else "Exited")
    m[2].metric("Lot size", fmt.na(info["fo_lot_size"]))
    m[3].metric("Sector", fmt.na(info["sector"]))
    _watch_toggle(m[4], int(info["id"]))

    recs = q.recommendations(days=3650, symbol=symbol)
    t_recs, t_news, t_fo, t_tech = st.tabs(["Published recommendations", "News", "F&O activity", "Technical screen"])

    with t_recs:
        st.caption("SOURCE RECOMMENDATIONS — full history with brokerage, analyst, target, stop loss, horizon and links.")
        chart = charts.target_history(recs)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
        event = ui.rec_table(recs.reset_index(drop=True), key="detail_recs")
        rows = event.selection.rows if event else []
        if rows:
            ui.rec_evidence(recs.reset_index(drop=True), rows,
                            q.recommendation_mentions(tuple(int(i) for i in recs.iloc[rows]["id"])))

    with t_news:
        news = q.news(days=3650, symbol=symbol, limit=500)
        settings = get_settings()
        if settings.ai_enabled and not news.empty and st.button("Generate AI digest of recent headlines"):
            from processing.ai.assistant import AIAssistant
            with st.spinner("Summarizing headlines…"):
                digest = AIAssistant(settings).summarize_headlines(info["name"], news["headline"].head(40).tolist())
            if digest:
                st.info("**AI SUMMARY** (machine-generated from headlines; not a recommendation; may contain errors)")
                st.markdown(digest)
        latest, history = news.head(15), news.iloc[15:]
        st.subheader("Latest")
        ui.news_list(latest, collapse_clusters=False)
        if not history.empty:
            with st.expander(f"Historical news ({len(history)})"):
                ui.news_list(history, collapse_clusters=False, limit=300)

    with t_fo:
        fo = d["fo"]
        if fo.empty:
            st.info("No F&O activity loaded yet.")
        else:
            f = fo.iloc[0]
            cols = st.columns(4)
            cols[0].metric("Open interest (contracts)", f"{f['oi_contracts']:,.0f}" if pd.notna(f["oi_contracts"]) else "N/A")
            cols[1].metric("OI change (shares)", f"{f['oi_change']:,.0f}")
            cols[2].metric("Contracts traded", f"{f['total_contracts']:,.0f}")
            cols[3].metric("Notional turnover", fmt.crore(f["turnover"]))
            st.caption(f"Stock futures + options, NSE F&O bhavcopy (EOD) {f['trade_date']}.")
        if not prices.empty:
            st.altair_chart(charts.price_line(prices), width="stretch")

    with t_tech:
        tech = d["tech"]
        if tech.empty:
            st.info("No technical snapshot yet.")
        else:
            st.dataframe(tech[["timeframe", "bar_time", "close", "rsi", "adx", "supertrend", "ema20", "vwap", "setup", "data_source"]]
                         .assign(bar_time=tech["bar_time"].map(fmt.ist)), hide_index=True, width="stretch")
            st.caption("Indicator conditions only — not a recommendation.")


def _watch_toggle(col, stock_id: int) -> None:
    wl = q.watchlist()
    watching = stock_id in set(wl["stock_id"])
    if col.button("★ Remove from watchlist" if watching else "☆ Add to watchlist"):
        with closing(connect()) as conn:
            repo = Repository(conn)
            repo.watchlist_remove(stock_id) if watching else repo.watchlist_add(stock_id)
        q.clear_caches()
        st.rerun()

from __future__ import annotations

import json
from contextlib import closing

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q
from dashboard import style


def _rebuild() -> None:
    from analysis.market import run_market_snapshot
    from config.settings import get_settings
    from database.connection import connect
    from database.repository import Repository

    with closing(connect()) as conn:
        run_market_snapshot(Repository(conn), get_settings())
    q.clear_caches()


@st.fragment(run_every="60s")
def _live_indices() -> None:
    ui.live_index_tiles()


def render() -> None:
    st.title("Market Analysis")
    style.banner("Updated every hour from 09:00 to 16:00 IST on trading days. Every point below is a fact computed "
                 "from stored data — indices, breadth, sectors, volatility, technical setups, news flow, published "
                 "research and F&O activity. No forecasts and no buy/sell calls.")
    snaps = q.market_snapshots()
    c1, c2 = st.columns([4, 1])
    if c2.button("⟳ Rebuild now", width="stretch"):
        with st.spinner("Building snapshot…"):
            _rebuild()
        st.rerun()
    if snaps.empty:
        st.info("No snapshot yet — click **Rebuild now** or run `python worker.py --once --job market`.")
        return
    options = snaps["id"].tolist()
    label = {r.id: fmt.ist(r.taken_at) for r in snaps.itertuples()}
    chosen = c1.selectbox("Snapshot", options, format_func=label.get)
    row = snaps[snaps["id"] == chosen].iloc[0]
    snap = json.loads(row["payload"])

    # Indices: always live (the snapshot's own index levels are frozen at its hour; see the timeline below)
    st.subheader("📊 Indices")
    _live_indices()

    if snap.get("explanation"):
        ui.market_observation(snap["explanation"])

    left, right = st.columns([3, 2])
    with left:
        st.subheader("📝 Observations")
        for o in snap.get("observations", []):
            st.markdown(f"- {o}")
        if isinstance(row["ai_summary"], str) and row["ai_summary"]:
            with st.container(border=True):
                st.caption(f"🤖 AI SUMMARY ({row['ai_model']}) — machine-generated from the facts above; may contain "
                           "errors; not a recommendation")
                st.text(row["ai_summary"])
    with right:
        b = snap.get("breadth")
        if b:
            st.subheader("🌡️ F&O breadth")
            st.caption(f"Source: {snap.get('breadth_source')}")
            style.ratio_bar([("▲", b["advances"], style.GREEN), ("■", b["unchanged"], style.GREY), ("▼", b["declines"], style.RED)])
            m = st.columns(3)
            m[0].metric("Advancing", b["advances"])
            m[1].metric("Declining", b["declines"])
            if "above_vwap" in b:
                m[2].metric("Above VWAP", f"{b['above_vwap']} / {b['total']}")
        tech = snap.get("technical", {})
        if tech:
            st.subheader("📐 Technical setups")
            t = st.columns(2)
            t[0].metric("Bullish (5m / 1D)", f"{tech.get('5m_BULLISH', 0)} / {tech.get('1d_BULLISH', 0)}")
            t[1].metric("Bearish (5m / 1D)", f"{tech.get('5m_BEARISH', 0)} / {tech.get('1d_BEARISH', 0)}")

    s1, s2, s3 = st.columns(3)
    with s1:
        st.subheader("🏭 Sectors")
        sectors = pd.DataFrame(snap.get("sectors", []))
        if not sectors.empty:
            sectors = sectors.rename(columns={"sector": "Sector", "avg_change_pct": "Avg chg %", "count": "Stocks"})
            st.dataframe(style.styled(sectors, change_cols=["Avg chg %"], formats={"Avg chg %": "{:+.2f}%"}),
                         hide_index=True, width="stretch", height=380)
    with s2:
        st.subheader("🚀 Top gainers")
        g = pd.DataFrame(snap.get("top_gainers", []))
        if not g.empty:
            st.dataframe(style.styled(g.rename(columns={"change_pct": "Chg %"}), change_cols=["Chg %"], formats={"Chg %": "{:+.2f}%"}),
                         hide_index=True, width="stretch")
        st.subheader("📉 Top losers")
        lo = pd.DataFrame(snap.get("top_losers", []))
        if not lo.empty:
            st.dataframe(style.styled(lo.rename(columns={"change_pct": "Chg %"}), change_cols=["Chg %"], formats={"Chg %": "{:+.2f}%"}),
                         hide_index=True, width="stretch")
    with s3:
        st.subheader("🏦 Published ratings (24h)")
        ratings = snap.get("published_ratings_24h", {})
        if ratings:
            pills = "".join(style.pill(f"{k}: {v}", style.GREEN if k in ("BUY", "ACCUMULATE") else
                                       style.RED if k in ("SELL", "REDUCE") else style.AMBER) for k, v in sorted(ratings.items()))
            st.markdown(pills, unsafe_allow_html=True)
        else:
            st.caption("None in the last 24 hours.")
        st.subheader("🔥 Most active F&O")
        fo = pd.DataFrame(snap.get("fo_most_active", []))
        if not fo.empty:
            fo["turnover"] = fo["turnover"] / 1e7
            st.dataframe(fo.rename(columns={"total_contracts": "Contracts", "turnover": "₹ cr"}), hide_index=True,
                         width="stretch", column_config={"Contracts": st.column_config.NumberColumn(format="localized"),
                                                         "₹ cr": st.column_config.NumberColumn(format="localized")})
            st.caption(f"NSE EOD {snap.get('fo_date', '')}")

    st.subheader("📰 Key market headlines")
    for h in snap.get("key_headlines", []):
        url = fmt.safe_url(h.get("url"))
        st.markdown((f"- [{h['headline']}]({url})" if url else f"- {h['headline']}") +
                    f" — *{h['publisher']} · {h['category']} · {fmt.ist(h['sort_ts'])}*")

    st.subheader("🕐 Hourly timeline")
    rows = []
    for r in snaps.itertuples():
        p = json.loads(r.payload)
        nifty = next((i for i in p.get("indices", []) if i["index_name"] == "Nifty 50"), {})
        br = p.get("breadth", {})
        rows.append({"Time (IST)": fmt.ist(r.taken_at), "Nifty 50": nifty.get("level"), "Nifty chg %": nifty.get("change_pct"),
                     "Advancing": br.get("advances"), "Declining": br.get("declines"),
                     "Bullish 5m": p.get("technical", {}).get("5m_BULLISH"), "Bearish 5m": p.get("technical", {}).get("5m_BEARISH")})
    timeline = pd.DataFrame(rows)
    st.dataframe(style.styled(timeline, change_cols=["Nifty chg %"], formats={"Nifty chg %": "{:+.2f}%", "Nifty 50": "{:,.2f}"}),
                 hide_index=True, width="stretch")

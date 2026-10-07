from __future__ import annotations

import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q

@st.fragment(run_every="60s")
def _live_market() -> None:
    ui.live_index_tiles()
    ui.market_observation(q.market_observation())


def render() -> None:
    st.title("Market Overview")
    st.caption(ui.DISCLAIMER)

    _live_market()

    c = q.counts()
    state = q.app_state()
    m = st.columns(5)
    m[0].metric("F&O stocks tracked", c["stocks"])
    m[1].metric("New published recommendations (24h)", c["recs_24h"])
    m[2].metric("Recommendations (7 days)", c["recs_7d"])
    m[3].metric("F&O-relevant news (24h)", c["news_24h"])
    m[4].metric("Sources active", f"{c['sources_active']} / {c['sources_enabled']}")
    st.caption(
        f"Last refresh — news: {fmt.ist(state.get('news_refreshed_at'))} · "
        f"EOD prices: {fmt.ist(state.get('prices_refreshed_at'))} · "
        f"intraday technicals: {fmt.ist(state.get('intraday_refreshed_at'))} · "
        f"F&O universe: {fmt.ist(state.get('universe_refreshed_at'))}"
    )

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Latest market news")
        ui.news_list(q.news(days=2, limit=60), collapse_clusters=True, limit=15)
    with right:
        st.subheader("Latest published recommendations")
        recs = q.recommendations(days=7)
        if recs.empty:
            st.info("No published recommendations in the last 7 days.")
        for _, r in recs.head(12).iterrows():
            url = fmt.safe_url(r["article_url"])
            who = " / ".join(x for x in (r["brokerage"], r["analyst"]) if isinstance(x, str)) or "N/A"
            line = (f"**{r['symbol']}** — {fmt.action_label(r['normalized_action'], r['original_action'])} · "
                    f"{who} · target {fmt.price(r['target_price'])}")
            st.markdown(f"{line}  \n[{r['source_name'] or 'source'} ↗]({url}) · {fmt.ist(r['published_at'], False)}"
                        if url else line)

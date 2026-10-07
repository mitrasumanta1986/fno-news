"""Indian F&O News & Research Dashboard — Streamlit entry point.

    streamlit run app.py

Data is collected by the separate worker process (python worker.py). This app only reads the
database, plus local watchlist/flag edits. There is no broker connection and no order code.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Indian F&O News & Research Dashboard", page_icon="📰", layout="wide")

from config.settings import BASE_DIR  # noqa: E402
from dashboard import formatting as fmt  # noqa: E402
from dashboard import nav  # noqa: E402
from dashboard import queries as q  # noqa: E402
from dashboard import style  # noqa: E402
from dashboard.views import (fo_activity, fo_stocks, intraday, market_analysis, news, overview,  # noqa: E402
                             recommendations, research_summary, search, source_status, stock_analysis, stock_detail,
                             technical, watchlist)
from jobs.tasks import init_database  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


@st.cache_resource
def _bootstrap() -> bool:
    setup_logging("app")
    init_database()
    return True


def _start_refresh(job: str) -> None:
    """Runs the worker once in a separate process so the UI stays responsive."""
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "refresh.log", "a", encoding="utf-8") as out:
        subprocess.Popen([sys.executable, str(Path(BASE_DIR) / "worker.py"), "--once", "--job", job],
                         cwd=BASE_DIR, stdout=out, stderr=subprocess.STDOUT)


_bootstrap()
style.inject()

nav.PAGES.update({
    "overview": st.Page(overview.render, title="Market Overview", icon="🏠", url_path="overview", default=True),
    "market": st.Page(market_analysis.render, title="Market Analysis (hourly)", icon="🧭", url_path="market-analysis"),
    "analysis": st.Page(stock_analysis.render, title="F&O Stock Analysis", icon="🧪", url_path="stock-analysis"),
    "intraday": st.Page(intraday.render, title="Intraday F&O", icon="⚡", url_path="intraday"),
    "stocks": st.Page(fo_stocks.render, title="All F&O Stocks", icon="📋", url_path="stocks"),
    "news": st.Page(news.render, title="Latest News", icon="📰", url_path="news"),
    "recs": st.Page(recommendations.render, title="Brokerage Recommendations", icon="🏦", url_path="recommendations"),
    "detail": st.Page(stock_detail.render, title="Stock Detail", icon="🔎", url_path="stock"),
    "summary": st.Page(research_summary.render, title="Published Research Summary", icon="📊", url_path="summary"),
    "fo": st.Page(fo_activity.render, title="F&O Activity (Top 10)", icon="📈", url_path="fo-activity"),
    "tech": st.Page(technical.render, title="Technical Screen", icon="📐", url_path="technical"),
    "search": st.Page(search.render, title="Search", icon="🔍", url_path="search"),
    "watch": st.Page(watchlist.render, title="Watchlist", icon="⭐", url_path="watchlist"),
    "status": st.Page(source_status.render, title="Source Status", icon="🩺", url_path="sources"),
})

page = st.navigation({
    "Dashboard": [nav.PAGES[k] for k in ("overview", "stocks", "news", "recs", "detail", "summary")],
    "Analysis": [nav.PAGES[k] for k in ("market", "analysis", "intraday")],
    "Market data": [nav.PAGES["fo"], nav.PAGES["tech"]],
    "Tools": [nav.PAGES[k] for k in ("search", "watch", "status")],
})

with st.sidebar:
    state = q.app_state()
    st.caption(f"News refreshed: {fmt.ist(state.get('news_refreshed_at'))}")
    st.caption(f"EOD data: {fmt.ist(state.get('prices_refreshed_at'))}")
    job = st.selectbox("Refresh now", ["news", "technical", "market", "prices", "fundamentals", "universe"],
                       label_visibility="collapsed",
                       format_func={"news": "News & recommendations", "technical": "Intraday bars & technicals",
                                    "market": "Market analysis snapshot", "prices": "EOD prices / F&O / daily screen",
                                    "fundamentals": "Fundamentals (slow)", "universe": "F&O universe"}.get)
    if st.button("↻ Refresh now", width="stretch"):
        _start_refresh(job)
        st.toast(f"Started '{job}' refresh in the background. Reload in a minute; see Source Status for results.")
    if st.button("Reload data", width="stretch"):
        q.clear_caches()
        st.rerun()
    st.divider()
    st.caption("Research aggregator only. No broker connection, no orders, no recommendations of its own.")

page.run()

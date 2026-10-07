"""Renders every dashboard page headlessly (Streamlit AppTest) and fails on any exception."""
import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import ROOT

VIEWS = ["overview", "fo_stocks", "news", "recommendations", "stock_detail", "research_summary",
         "fo_activity", "technical", "search", "watchlist", "source_status", "market_analysis", "stock_analysis",
         "intraday"]

SCRIPT = """
import sys
sys.path.insert(0, {root!r})
from dashboard import nav
from dashboard.views import {view} as view
nav.PAGES.setdefault("detail", None)
view.render()
"""


def render(view: str) -> AppTest:
    at = AppTest.from_string(SCRIPT.format(root=str(ROOT), view=view), default_timeout=60)
    at.run()
    return at


@pytest.mark.parametrize("view", VIEWS)
def test_page_renders_on_empty_and_seeded_db(temp_db, view):
    from config.settings import get_settings
    from processing.pipeline import build_context, process_items
    from sources.base import RawItem

    process_items(temp_db, temp_db.ensure_source("Seed", "rss"),
                  [RawItem("Buy Petronet LNG; target of Rs 360: Emkay Global Financial", "https://x.test/1", "Moneycontrol"),
                   RawItem("Sensex falls 700 points as FIIs sell", "https://x.test/2", "Mint")],  # no stock, no snippet
                  build_context(temp_db, get_settings()))
    at = render(view)
    assert not at.exception, [e.value for e in at.exception]

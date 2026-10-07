"""One failing source must not affect others; no broker/trading code may exist in the project."""
import re
from pathlib import Path

import responses

from config.settings import get_settings
from jobs import tasks
from processing.pipeline import build_context
from sources.base import SourceConfig

ROOT = Path(__file__).resolve().parent.parent

GOOD_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Buy Petronet LNG; target of Rs 360: Emkay Global Financial</title><link>https://good.test/a</link>
<pubDate>Mon, 28 Sep 2026 10:10:01 +0530</pubDate></item></channel></rss>"""


def _cfg(name, url):
    return SourceConfig(name=name, type="rss", publisher=name, feeds=[url], interval_minutes=10)


@responses.activate
def test_failed_source_isolated(temp_db, monkeypatch):
    tasks._client = None
    responses.add(responses.GET, "https://good.test/robots.txt", status=404)
    responses.add(responses.GET, "https://good.test/feed.xml", body=GOOD_FEED)
    responses.add(responses.GET, "https://bad.test/robots.txt", status=404)
    responses.add(responses.GET, "https://bad.test/feed.xml", status=500)
    responses.add(responses.GET, "https://blocked.test/robots.txt", body="User-agent: *\nDisallow: /")
    responses.add(responses.GET, "https://limited.test/robots.txt", status=404)
    responses.add(responses.GET, "https://limited.test/feed.xml", status=429, headers={"Retry-After": "120"})
    monkeypatch.setattr("utils.ratelimit.DomainRateLimiter.wait", lambda self, domain: None)
    monkeypatch.setattr("urllib3.util.retry.Retry.sleep", lambda self, response=None: None)

    configs = [_cfg("Good", "https://good.test/feed.xml"), _cfg("Bad", "https://bad.test/feed.xml"),
               _cfg("Blocked", "https://blocked.test/feed.xml"), _cfg("Limited", "https://limited.test/feed.xml")]
    temp_db.sync_sources(configs)
    ctx = build_context(temp_db, get_settings())
    results = {c.name: tasks.run_source(c, ctx) for c in configs}

    assert results["Good"]["status"] == "ACTIVE" and results["Good"]["recs"] == 1
    assert results["Bad"]["status"] == "FAILED"
    assert results["Blocked"]["status"] == "BLOCKED"
    assert results["Limited"]["status"] == "RATE_LIMITED"
    statuses = dict(temp_db.conn.execute("SELECT name, status FROM sources").fetchall())
    assert statuses["Good"] == "ACTIVE" and statuses["Bad"] == "FAILED"
    assert temp_db.conn.execute("SELECT COUNT(*) FROM fetch_logs WHERE job='news'").fetchone()[0] == 4
    tasks._client = None


def test_no_broker_or_order_code():
    forbidden = re.compile(r"kiteconnect|dhanhq|upstox|smartapi|fyers|breeze_connect|place_order|placeorder", re.I)
    offenders = [p for p in ROOT.rglob("*.py")
                 if ".venv" not in p.parts and p.name != Path(__file__).name and forbidden.search(p.read_text(encoding="utf-8"))]
    assert offenders == []

"""End-to-end processing against a temporary database: dedup, relevance, cross-outlet merging."""
from datetime import datetime, timedelta, timezone

from config.settings import get_settings
from processing.pipeline import build_context, process_items
from sources.base import RawItem

NOW = datetime.now(timezone.utc)


def _item(title, url, publisher="Moneycontrol", minutes_ago=10, summary=None):
    return RawItem(title=title, url=url, publisher=publisher, summary=summary, published=NOW - timedelta(minutes=minutes_ago))


def _run(repo, items, source="Test"):
    source_id = repo.ensure_source(source, "rss")
    return process_items(repo, source_id, items, build_context(repo, get_settings()))


def test_duplicate_url_and_same_publisher_headline(temp_db):
    stats = _run(temp_db, [
        _item("Buy Petronet LNG; target of Rs 360: Emkay Global Financial", "https://mc.com/a?utm_source=x"),
        _item("Buy Petronet LNG; target of Rs 360: Emkay Global Financial", "https://mc.com/a"),
        _item("Buy Petronet LNG; target of Rs 360: Emkay Global Financial", "https://mc.com/a-copy"),
    ])
    assert stats["new"] == 1 and stats["duplicate"] == 2 and stats["recs"] == 1


def test_same_call_from_two_outlets_counted_once(temp_db):
    _run(temp_db, [_item("Petronet LNG shares: Nomura retains 'Buy', target price Rs 345", "https://cnbc.com/x",
                         publisher="CNBC-TV18", minutes_ago=60)])
    _run(temp_db, [_item("Nomura retains Buy on Petronet LNG with Rs 345 target", "https://et.com/y",
                         publisher="The Economic Times", minutes_ago=5)])
    recs = temp_db.conn.execute("SELECT id, source_name FROM recommendations").fetchall()
    assert len(recs) == 1
    assert recs[0]["source_name"] == "CNBC-TV18"  # earliest report found
    mentions = temp_db.conn.execute("SELECT COUNT(*) FROM recommendation_mentions").fetchone()[0]
    assert mentions == 2
    clusters = temp_db.conn.execute("SELECT COUNT(DISTINCT story_cluster_id) FROM news").fetchone()[0]
    assert clusters in (1, 2)


def test_different_targets_are_separate_calls(temp_db):
    _run(temp_db, [_item("Buy Titan Company; target Rs 4,000: Motilal Oswal", "https://a.com/1", minutes_ago=60)])
    _run(temp_db, [_item("Buy Titan Company; target Rs 4,400: Motilal Oswal", "https://a.com/2", minutes_ago=5)])
    assert temp_db.conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 2


def test_irrelevant_items_dropped_but_market_news_kept(temp_db):
    stats = _run(temp_db, [
        _item("Haryana child rescued from borewell after 10 hours", "https://a.com/h"),
        _item("Sensex falls 700 points, Nifty below 22,950 as FIIs sell", "https://a.com/m"),
        _item("HDFC Bank Q2 results: net profit rises 12%", "https://a.com/r"),
    ])
    assert stats["irrelevant"] == 1 and stats["new"] == 2
    cats = {r[0] for r in temp_db.conn.execute("SELECT category FROM news")}
    assert "Results" in cats


def test_missing_values_stored_as_null(temp_db):
    _run(temp_db, [_item("CLSA maintains outperform on HDFC Bank", "https://a.com/c")])
    r = temp_db.conn.execute("SELECT * FROM recommendations").fetchone()
    assert r["target_price"] is None and r["stop_loss"] is None and r["analyst_id"] is None
    assert r["original_action"].lower() == "outperform" and r["normalized_action"] == "BUY"
    assert r["extraction_method"] == "RULE" and r["evidence_text"]

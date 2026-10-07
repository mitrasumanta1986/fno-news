from utils.hashing import canonicalize_url, content_hash
from utils.robots import RobotsRules
from utils.timeutils import parse_datetime, to_iso

AGENT = "fnonewsdashboard"


def test_canonical_url_strips_tracking_and_fragment():
    a = canonicalize_url("http://WWW.Example.com/news/story-1/?utm_source=x&from=mdr#publisher=newsstand")
    b = canonicalize_url("https://www.example.com/news/story-1")
    assert a == b


def test_canonical_url_amp():
    assert canonicalize_url("https://x.com/a/b/amp") == canonicalize_url("https://x.com/a/b")


def test_content_hash_ignores_punctuation_and_case():
    assert content_hash("Buy HDFC Bank; target Rs 1,850") == content_hash("buy hdfc bank target rs 1 850")


def test_robots_wildcards_and_longest_match():
    rules = RobotsRules.from_text("""
User-agent: *
Allow: /
Disallow: /*balance-sheet/
Disallow: /market/sports
Disallow: /*.pdf$

User-agent: GPTBot
Disallow: /
""")
    assert rules.can_fetch(AGENT, "https://x.com/commonfeeds/v1/cne/rss/market.xml")
    assert not rules.can_fetch(AGENT, "https://x.com/company/abc/balance-sheet/")
    assert not rules.can_fetch(AGENT, "https://x.com/market/sports/cricket")
    assert not rules.can_fetch(AGENT, "https://x.com/file.pdf")
    assert rules.can_fetch(AGENT, "https://x.com/file.pdf?x=1")


def test_robots_specific_agent_group_and_allow_tie():
    rules = RobotsRules.from_text("User-agent: FnONewsDashboard\nDisallow: /private\nAllow: /private\n\nUser-agent: *\nDisallow: /")
    assert rules.can_fetch(AGENT, "https://x.com/private/page")
    assert rules.can_fetch(AGENT, "https://x.com/public")  # specific group has no matching disallow


def test_robots_disallow_all():
    rules = RobotsRules.from_text("User-agent: *\nDisallow: /")
    assert not rules.can_fetch(AGENT, "https://news.example.com/rss/search?q=x")


def test_date_parsing_formats():
    assert to_iso(parse_datetime("28-Sep-2026 10:11:55")) == "2026-09-28T04:41:55+00:00"  # NSE, IST
    assert to_iso(parse_datetime("Mon, 28 Sep 2026 10:10:01 +0530")) == "2026-09-28T04:40:01+00:00"
    assert to_iso(parse_datetime("2026-09-28T10:17:41+05:30")) == "2026-09-28T04:47:41+00:00"
    assert parse_datetime("not a date") is None

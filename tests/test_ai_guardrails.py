"""The AI helper may only return values that appear verbatim in the source text."""
from types import SimpleNamespace

from processing.ai.assistant import AIAssistant


def _assistant():
    return AIAssistant.__new__(AIAssistant)  # no client needed for verification


def _ctx(tagger, brokers, normalizer):
    return SimpleNamespace(tagger=tagger, brokers=brokers, normalizer=normalizer)


TEXT = "Jefferies has a buy call on HDFC Bank with a price target of Rs 2,050"


def test_verified_item_accepted(tagger, brokers, normalizer):
    item = {"company": "HDFC Bank", "rating_as_written": "buy", "brokerage_as_written": "Jefferies",
            "analyst_as_written": None, "target_price": 2050, "stop_loss": None, "time_horizon_as_written": None,
            "evidence_quote": "Jefferies has a buy call on HDFC Bank with a price target of Rs 2,050"}
    rec = _assistant()._verify(item, TEXT, _ctx(tagger, brokers, normalizer))
    assert rec and rec.symbol == "HDFCBANK" and rec.brokerage == "Jefferies" and rec.target_price == 2050 and rec.method == "AI"


def test_hallucinated_fields_dropped(tagger, brokers, normalizer):
    item = {"company": "HDFC Bank", "rating_as_written": "buy", "brokerage_as_written": "Jefferies",
            "analyst_as_written": "Invented Person", "target_price": 2200, "stop_loss": 1800,
            "time_horizon_as_written": "12 months", "evidence_quote": "Jefferies has a buy call on HDFC Bank"}
    rec = _assistant()._verify(item, TEXT, _ctx(tagger, brokers, normalizer))
    assert rec.analyst is None and rec.target_price is None and rec.stop_loss is None and rec.horizon is None


def test_invented_rating_or_evidence_rejected(tagger, brokers, normalizer):
    base = {"company": "HDFC Bank", "brokerage_as_written": "Jefferies", "analyst_as_written": None,
            "target_price": None, "stop_loss": None, "time_horizon_as_written": None}
    ctx = _ctx(tagger, brokers, normalizer)
    assert _assistant()._verify({**base, "rating_as_written": "sell", "evidence_quote": "Jefferies has a sell call"}, TEXT, ctx) is None
    assert _assistant()._verify({**base, "rating_as_written": "Accumulate",
                                 "evidence_quote": "Jefferies has a buy call on HDFC Bank"}, TEXT, ctx) is None

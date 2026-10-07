from processing.entities import build_alias_map, resolve_entities


def symbols(tagger, text):
    return [m.symbol for m in tagger.find(text)]


def test_longest_alias_wins(tagger):
    assert symbols(tagger, "L&T Finance shares rise") == ["LTF"]
    assert symbols(tagger, "L&T bags large order") == ["LT"]


def test_suffix_guard_blocks_other_company(tagger):
    assert symbols(tagger, "Mahindra and Mahindra Financial Services rallies") == []
    assert symbols(tagger, "Mahindra & Mahindra rallies") == ["M&M"]


def test_symbol_match_is_case_sensitive(tagger):
    assert symbols(tagger, "ITC shares gain") == ["ITC"]
    assert symbols(tagger, "the itc of the day") == []


def test_word_boundaries(tagger):
    assert symbols(tagger, "Titanic losses in markets") == []


def test_brokerage_vs_bank_overlap(tagger, brokers):
    text = "Kotak Institutional Equities maintains buy on Infosys"
    stocks, found = resolve_entities(tagger.find(text), brokers.find(text))
    assert [s.symbol for s in stocks] == ["INFY"]
    assert [b.name for b in found] == ["Kotak Institutional Equities"]
    text = "Kotak Bank shares: Nomura retains Buy"
    stocks, found = resolve_entities(tagger.find(text), brokers.find(text))
    assert [s.symbol for s in stocks] == ["KOTAKBANK"]
    assert [b.name for b in found] == ["Nomura"]


def test_equal_span_prefers_brokerage_when_other_stock(tagger, brokers):
    text = "Buy HDFC Bank: Sameet Chavan of Angel One"
    stocks, found = resolve_entities(tagger.find(text), brokers.find(text))
    assert [s.symbol for s in stocks] == ["HDFCBANK"]
    assert [b.name for b in found] == ["Angel One"]
    text = "Angel One shares jump 5% on strong client additions"
    stocks, found = resolve_entities(tagger.find(text), brokers.find(text))
    assert [s.symbol for s in stocks] == ["ANGELONE"]


def test_ambiguous_alias_dropped():
    alias_map = build_alias_map([(1, "AAA", "Alpha Industries Ltd."), (2, "BBB", "Alpha Industries Limited")], {})
    assert all(a.lower() != "alpha industries" for items in alias_map.values() for a, _ in items)


def test_action_normalization(normalizer):
    assert normalizer.action("Accumulate") == "ACCUMULATE"
    assert normalizer.action("Market Perform") == "NEUTRAL"
    assert normalizer.action("market-perform") == "NEUTRAL"
    assert normalizer.action("Equal-Weight") == "NEUTRAL"
    assert normalizer.action("Underweight") == "SELL"
    assert normalizer.action("Outperform") == "BUY"
    assert normalizer.action("Reduce") == "REDUCE"
    assert normalizer.action("Book profit") == "UNMAPPED"


def test_horizon_normalization(normalizer):
    assert normalizer.horizon("for the next 12 months") == ("12 months", "LONG")
    assert normalizer.horizon("an intraday trade") == ("intraday", "INTRADAY")
    assert normalizer.horizon("no horizon here") == (None, None)

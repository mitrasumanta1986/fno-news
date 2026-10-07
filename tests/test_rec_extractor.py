"""Golden tests built from real headline patterns seen on ET, Moneycontrol and CNBC-TV18."""
import pytest

# headline, snippet, expected list of (symbol, normalized, brokerage, target, stop_loss)
CASES = [
    ("Buy Petronet LNG; target of Rs 360: Emkay Global Financial", None,
     [("PETRONET", "BUY", "Emkay Global", 360.0, None)]),
    ("Accumulate Petronet LNG; target of Rs 302: Prabhudas Lilladher", None,
     [("PETRONET", "ACCUMULATE", "Prabhudas Lilladher", 302.0, None)]),
    ("Petronet LNG shares: Nomura retains 'Buy', target price Rs 345; Kochi pipeline seen driving utilisation", None,
     [("PETRONET", "BUY", "Nomura", 345.0, None)]),
    ("Dr Reddy's shares gain over 1% after Nomura retains 'Buy'; Rs1,740 target, key biologics milestones ahead", None,
     [("DRREDDY", "BUY", "Nomura", 1740.0, None)]),
    ("Citi maintains sell on Hindustan Zinc; Motilal Oswal raises target price on Gopal Snacks", None,
     [("HINDZINC", "SELL", "Citi", None, None)]),
    # Roundup: the only F&O stock is in the SECOND clause; the first clause's rating must not leak into it.
    ("Morgan Stanley maintains underweight on Dixon Ltd; Citi cuts target price on IndiGo", None, []),
    ("Buy, Sell or Hold: Citi recommends buy on Maruti Suzuki; Nuvama sees over 20% upside in BEL", None,
     [("MARUTI", "BUY", "Citi", None, None)]),
    ("Sell or Hold: ICICI Securities maintains Hold on NSDL; Motilal Oswal maintains Buy on L&T", None,
     [("LT", "BUY", "Motilal Oswal", None, None)]),
    ("Morgan Stanley remains overweight on Titan Company", None, [("TITAN", "BUY", "Morgan Stanley", None, None)]),
    ("Morgan Stanley recommends underweight on L&T Finance", None, [("LTF", "SELL", "Morgan Stanley", None, None)]),
    ("Nomura initiated coverage on Tata Steel with a 'buy' rating and a price target of Rs 215", None,
     [("TATASTEEL", "BUY", "Nomura", 215.0, None)]),
    ("Buy HDFC Bank; target Rs 1,850, stop loss Rs 1,720: Sameet Chavan of Angel One", None,
     [("HDFCBANK", "BUY", "Angel One", 1850.0, 1720.0)]),
    ("Elara recommends Accumulate on Kotak Bank", None, [("KOTAKBANK", "ACCUMULATE", "Elara Capital", None, None)]),
    ("Morgan Stanley upgrades Infosys to Equal-weight, raises target to Rs 1,700", None,
     [("INFY", "NEUTRAL", "Morgan Stanley", 1700.0, None)]),
    # Must NOT produce a recommendation:
    ("Accumulate Mahindra and Mahindra Financial Services; target of Rs 350: Prabhudas Lilladher", None, []),
    ("Tata Steel, JSW Steel in focus as rebar prices rally; Nomura retains 'Buy'", None, []),
    ("HAL shares plummet 9% after Tejas crash. Should you buy the dip?", None, []),
    ("Foreign investors buy ₹1,617 crore of Indian shares after a day of heavy selling", None, []),
    ("ITC announces share buyback worth Rs 10,000 crore", None, []),
    ("Infosys shares rise 3% ahead of Q2 results", None, []),
    ("Stocks to buy: Titan, ITC among picks with target upside", None, []),
    ("Buy or sell: Should you hold HDFC Bank after results?", None, []),
]


@pytest.mark.parametrize("headline,snippet,expected", CASES)
def test_extraction(extractor, headline, snippet, expected):
    recs = extractor.extract(headline, snippet)
    got = [(r.symbol, r.normalized_action, r.brokerage, r.target_price, r.stop_loss) for r in recs]
    assert got == expected


def test_original_wording_kept(extractor):
    rec = extractor.extract("CLSA maintains outperform on HDFC Bank")[0]
    assert rec.original_action.lower() == "outperform"
    assert rec.normalized_action == "BUY"
    assert rec.rating_change == "MAINTAIN"
    assert rec.evidence_text == "CLSA maintains outperform on HDFC Bank"


def test_analyst_attribution(extractor):
    rec = extractor.extract("Buy HDFC Bank; target Rs 1,850, stop loss Rs 1,720: Sameet Chavan of Angel One")[0]
    assert rec.analyst == "Sameet Chavan"


def test_missing_fields_stay_none(extractor):
    rec = extractor.extract("Citi maintains buy on ICICI Bank" if False else "Goldman Sachs maintains buy on L&T")[0]
    assert rec.target_price is None and rec.stop_loss is None and rec.horizon is None and rec.analyst is None


def test_horizon_only_when_published(extractor):
    rec = extractor.extract("Buy Titan Company; target Rs 4,000 in 12 months: Motilal Oswal")[0]
    assert rec.horizon == "LONG" and rec.horizon_original == "12 months"


def test_snippet_supplements_single_stock(extractor):
    rec = extractor.extract("CLSA maintains outperform on HDFC Bank",
                            "The brokerage has a target price of Rs 2,100 on the lender.")[0]
    assert rec.target_price == 2100.0


def test_snippet_about_other_company_ignored(extractor):
    rec = extractor.extract("CLSA maintains outperform on HDFC Bank",
                            "Separately, it set a target price of Rs 900 for ITC.")[0]
    assert rec.target_price is None

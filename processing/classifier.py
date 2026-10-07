"""Rule-based news categorisation (first matching rule wins)."""
from __future__ import annotations

import re

CATEGORIES = [
    "Brokerage Research", "Analyst Recommendation", "Results", "Order Win", "Order Book",
    "Management Commentary", "Corporate Action", "M&A", "Fundraising", "Regulatory", "Sector News",
    "Dividend", "Bonus", "Split", "Promoter Activity", "FII/DII", "General Market", "Other",
]

MARKET_RX = re.compile(
    r"\b(?:sensex|nifty|stock\s+market|markets?|dalal\s+street|f&o|derivatives?|expiry|rupee|bond\s+yields?|"
    r"indices|shares?|stocks?|equit(?:y|ies)|vix|fiis?|fpis?|diis?)\b", re.I)

# Market-wide categories kept even when no specific F&O stock is mentioned.
MARKET_WIDE = {"General Market", "FII/DII", "Sector News", "Regulatory"}

_RULES: list[tuple[str, re.Pattern]] = [(name, re.compile(rx, re.I)) for name, rx in [
    ("Dividend", r"\bdividends?\b"),
    ("Bonus", r"\bbonus\s+(?:issue|shares?|equity)\b"),
    ("Split", r"\b(?:stock|share|face\s+value)\s+split\b|\bsub-?division\b|\bsplit\s+(?:ratio|record)\b"),
    ("Results", r"\bq[1-4](?:\s*fy\s*\d{2,4})?\b|\bresults?\b|\bearnings\b|\bnet\s+profit\b|\bprofit\s+(?:rises|falls|jumps|drops|surges|declines)\b|\bpat\b|\bebitda\b|\bquarterly\b"),
    ("Order Win", r"\b(?:bags?|bagged|wins?|won|secures?|secured|receives?|received|grabs?|lands?|bagging|winning)\b[^.;|]{0,60}?\b(?:orders?|contracts?|projects?|deals?)\b|\bletter\s+of\s+(?:award|intent)\b|\border\s+worth\b"),
    ("Order Book", r"\border\s*(?:book|backlog|inflows?|pipeline)\b"),
    ("M&A", r"\bacqui(?:re|res|red|ring|sition|sitions)\b|\bmergers?\b|\bmerge[sd]?\b|\bamalgamation\b|\btakeover\b|\bdemerger\b|\bstake\s+(?:sale|acquisition)\b|\bscheme\s+of\s+arrangement\b"),
    ("Fundraising", r"\bqip\b|\braises?\b[^.;|]{0,30}\b(?:crore|funds?|capital|bn|billion|million)\b|\bfund\s*-?\s*rais\w*|\bncds?\b|\bpreferential\s+(?:issue|allotment)\b|\brights\s+issue\b|\bipo\b|\bofs\b|\boffer\s+for\s+sale\b"),
    ("Promoter Activity", r"\bpromoters?\b|\bpledg\w*\b|\binsider\b|\bblock\s+deals?\b|\bbulk\s+deals?\b|\bstake\s+(?:hike|increase|cut)\b|\bsast\b"),
    ("FII/DII", r"\bfiis?\b|\bfpis?\b|\bdiis?\b|\bforeign\s+(?:portfolio\s+|institutional\s+)?investors?\b|\bdomestic\s+institutional\b"),
    ("Regulatory", r"\bsebi\b|\brbi\b|\bpenalty\b|\bfined\b|\bshow[\s-]cause\b|\btax\s+(?:demand|notice)\b|\bgst\s+(?:demand|notice)\b|\bcci\b|\bnclt\b|\bnclat\b|\bsupreme\s+court\b|\bhigh\s+court\b|\busfda\b|\bwarning\s+letter\b|\bform\s+483\b|\bregulat\w+\b|\bprobe\b"),
    ("Corporate Action", r"\brecord\s+date\b|\bex-?date\b|\bboard\s+meeting\b|\bagm\b|\begm\b|\bbuy-?back\b|\bdelist\w*\b|\bpostal\s+ballot\b|\bcorporate\s+action\b"),
    ("Management Commentary", r"\b(?:ceo|cfo|md|chairman|chairperson|founder|management)\b|\bguidance\b|\bcon-?call\b|\binterview\b|\boutlook\b"),
    ("Sector News", r"\bsector(?:al)?\b|\bindustry\b|\b(?:bank(?:ing)?|it|pharma|auto|metal|fmcg|realty|psu|oil|cement|power|defen[cs]e|telecom|infra)\s+stocks?\b"),
    ("General Market", MARKET_RX.pattern),
]]

_RESEARCH_HINT = re.compile(r"\b(?:target|rating|coverage|upgrade|downgrade|outperform|underperform|overweight|underweight|upside|downside|valuation|price\s+objective)\b", re.I)


def classify(text: str, *, has_recommendation: bool, has_brokerage: bool, rec_has_brokerage: bool) -> str:
    if has_recommendation:
        return "Brokerage Research" if rec_has_brokerage else "Analyst Recommendation"
    if has_brokerage and _RESEARCH_HINT.search(text):
        return "Brokerage Research"
    for name, rx in _RULES:
        if rx.search(text):
            return name
    return "Other"

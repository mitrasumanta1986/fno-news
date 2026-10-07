"""Rule-based extraction of PUBLISHED recommendations from headlines/snippets.

A recommendation is recorded only when the text explicitly states a rating for exactly one
F&O stock, in a recognised context (e.g. "Buy HDFC Bank; target Rs 1,850: ICICI Securities",
"Nomura retains 'Buy' on Petronet LNG", "Jefferies upgrades Infosys to Buy"). Missing fields
stay None (N/A). Nothing is inferred or guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from processing.entities import BrokerageMatch, BrokerageMatcher, StockMatch, StockTagger, resolve_entities
from processing.normalizer import Normalizer, term_pattern

_Q_OPEN = "['\"‘“]"
_Q_CLOSE = "['\"’”]"
_B = r"(?<![\w-])"
_E = r"(?![\w-])"
_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CUR = r"(?:rs\.?|₹|inr)\s*"
_NOT_PRICE_TAIL = r"(?!\d|[.,]\d)(?!\s*(?:%|per\s*cent|percent|crore|cr\b|lakh|lk\b|bn\b|billion|mn\b|million|trillion|x\b|times|pts|points|bps))"
_META_PREFIX = re.compile(
    r"^\s*(?:(?:buy|sell|hold)(?:\s*,\s*|\s*,?\s+or\s+)(?:buy|sell|hold)(?:(?:\s*,\s*|\s*,?\s+or\s+)(?:buy|sell|hold))?|"
    r"stocks?\s+to\s+(?:buy|sell|watch)(?:\s+today)?|stock\s+picks?(?:\s+today)?|top\s+picks?|trade\s+setup|"
    r"technical\s+picks?)\s*[:\-–|]\s*", re.I)
# A clause that only continues the previous one with price details, e.g. "; target of Rs 360: Emkay"
_CONTINUATION = re.compile(
    r"^\s*(?:(?:rs\.?|₹|inr)\s*\d[\d,]*(?:\.\d+)?\s+(?:price\s+)?target\b|target\b|tp\b|price\s+target\b|"
    r"stop[\s-]?loss\b|sl\b|cmp\b|upside\b|downside\b)", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*[;|]\s*")
_MULTI_SPLIT = re.compile(r"\s*[;|:]\s*")
_BAD_PREFIX = re.compile(r"(?:\bfrom|\bstocks?\s+to|\bshould\s+you|\btime\s+to|\bwhether\s+to|\bwhy|\bor|\bnot|\bto\s+buy\s+or)\s*$", re.I)
_BAD_SUFFIX = re.compile(r"^\s*(?:,|/|\bor\b)\s*(?:buy|sell|hold)\b", re.I)
_NAME = r"[A-Z][a-zA-Z.'’-]+(?:\s+[A-Z][a-zA-Z.'’-]+){1,3}"
_CORP_WORDS = re.compile(
    r"\b(?:securities|capital|broking|brokers|financial|finance|research|equities|wealth|advisors|advisory|"
    r"investments?|markets|institutional|stock\s+broking|ltd|limited|group|global)\b", re.I)
_NAME_STOPWORDS = {"buy", "sell", "hold", "target", "shares", "share", "stock", "stocks", "rs", "nifty",
                   "sensex", "market", "price", "today", "analyst", "brokerage", "q1", "q2", "q3", "q4"}

_TARGET_KW = r"\b(?:target(?:\s+price)?|price\s+target|tp|fair\s+value|upside\s+(?:target\s+)?(?:to|of)|downside\s+(?:target\s+)?(?:to|of))\b"
_SL_KW = r"\b(?:stop[\s-]?loss|sl)\b"
_CMP_KW = r"\b(?:cmp|current\s+market\s+price)\b"


def _price_rx(keyword: str) -> re.Pattern:
    return re.compile(
        rf"{keyword}[^\d₹;|]{{0,30}}?(?:{_CUR})?{_NUM}(?:\s*(?:-|–|to)\s*(?:{_CUR})?{_NUM})?{_NOT_PRICE_TAIL}", re.I)


_TARGET_RX, _SL_RX, _CMP_RX = _price_rx(_TARGET_KW), _price_rx(_SL_KW), _price_rx(_CMP_KW)
# "Rs 1,740 target" (number before the keyword)
_TARGET_RX_AFTER = re.compile(rf"{_CUR}{_NUM}{_NOT_PRICE_TAIL}\s+(?:price\s+)?target\b", re.I)

_CHANGE_RX = [
    ("UPGRADE", re.compile(r"\bupgrade[sd]?\b", re.I)),
    ("DOWNGRADE", re.compile(r"\bdowngrade[sd]?\b", re.I)),
    ("INITIATE", re.compile(r"\b(?:initiat\w*|resum\w*|reinstat\w*)\b", re.I)),
    ("MAINTAIN", re.compile(r"\b(?:retain\w*|maintain\w*|reiterat\w*|keep|keeps|kept|keeping|remains?|remained|stays?)\b", re.I)),
]


@dataclass
class ExtractedRec:
    stock_id: int
    symbol: str
    original_action: str
    normalized_action: str
    rating_change: str = "N/A"
    brokerage: str | None = None
    analyst: str | None = None
    target_price: float | None = None
    target_text: str | None = None
    stop_loss: float | None = None
    price_at_reco: float | None = None
    horizon_original: str | None = None
    horizon: str | None = None
    evidence_text: str = ""
    confidence: float = 0.5
    method: str = "RULE"
    brokerage_spans: list[BrokerageMatch] = field(default_factory=list, repr=False)


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    return number if 1 <= number < 1_000_000 else None


def _find_price(rx: re.Pattern, text: str) -> tuple[float | None, str | None]:
    m = rx.search(text)
    if not m:
        if rx is _TARGET_RX:
            return _find_price(_TARGET_RX_AFTER, text)
        return None, None
    low = _to_float(m.group(1))
    return low, m.group(0).strip() if low is not None else None


class RecommendationExtractor:
    def __init__(self, tagger: StockTagger, brokers: BrokerageMatcher, normalizer: Normalizer):
        self.tagger = tagger
        self.brokers = brokers
        self.normalizer = normalizer
        all_terms = "|".join(term_pattern(t) for t in normalizer.all_terms)
        strong = "|".join(term_pattern(t) for t in normalizer.strong_terms)
        imperative_terms = [t for t in normalizer.all_terms if t not in {"positive", "negative", "top pick", "inline"}]
        imperative = "|".join(term_pattern(t) for t in imperative_terms)
        verbs = (r"retain|retains|retained|maintain|maintains|maintained|reiterate|reiterates|reiterated|keep|keeps|kept|"
                 r"assign|assigns|assigned|rate|rates|rated|recommend|recommends|recommended|suggest|suggests|suggested|"
                 r"advise|advises|advised|has|have|with|give|gives|remain|remains|remained|stay|stays|stayed")
        changes = (r"upgrade[sd]?|downgrade[sd]?|initiate[sd]?|initiating|resume[sd]?|reinstate[sd]?|turns?|turned|"
                   r"moves?|moved|raises?|raised|cuts?|lowers?|lowered|revises?|revised")
        self._imperative = re.compile(rf"^\s*(?P<a>{imperative}){_E}", re.I)
        self._contexts = [
            ("quoted", re.compile(rf"{_Q_OPEN}(?P<a>{all_terms}){_Q_CLOSE}", re.I)),
            ("verb", re.compile(rf"\b(?:{verbs})\s+(?:(?:a|an|its|their|the)\s+)?{_Q_OPEN}?(?P<a>{strong}){_Q_CLOSE}?{_E}", re.I)),
            ("change", re.compile(rf"\b(?:{changes})\b[^;:|]{{0,80}}?\b(?:to|with|at)\s+(?:(?:a|an)\s+)?{_Q_OPEN}?(?P<a>{strong}){_Q_CLOSE}?{_E}", re.I)),
            ("suffix", re.compile(rf"{_B}{_Q_OPEN}?(?P<a>{all_terms}){_Q_CLOSE}?\s+(?:rating|call|stance|recommendation|tag){_E}", re.I)),
        ]

    # ------------------------------------------------------------------ public
    def extract(self, headline: str, snippet: str | None = None) -> list[ExtractedRec]:
        text = _META_PREFIX.sub("", headline or "").strip()
        if not text:
            return []
        stocks, _ = resolve_entities(self.tagger.find(text), self.brokers.find(text))
        unique_ids = {s.stock_id for s in stocks}
        results: list[ExtractedRec] = []
        if len(unique_ids) == 1:
            unit = self._single_stock_unit(text)
            if unit:
                u_stocks, u_brokers = self._entities(unit)
                if u_stocks:
                    rec = self._from_unit(unit, u_stocks, u_brokers, allow_trailing_attribution=True)
                    if rec:
                        if unit == text:  # snippets of multi-clause roundups may discuss other companies
                            self._supplement_from_snippet(rec, snippet)
                        results.append(rec)
        elif len(unique_ids) > 1:
            for unit in _MULTI_SPLIT.split(text):
                u_stocks, u_brokers = self._entities(unit)
                if len({s.stock_id for s in u_stocks}) == 1:
                    rec = self._from_unit(unit, u_stocks, u_brokers, allow_trailing_attribution=False)
                    if rec:
                        results.append(rec)
        if not results and snippet:
            results.extend(self._from_snippet(snippet))
        # One published call per stock per article
        by_stock: dict[int, ExtractedRec] = {}
        for r in results:
            by_stock.setdefault(r.stock_id, r)
        return list(by_stock.values())

    # ------------------------------------------------------------------ internals
    def _entities(self, text: str) -> tuple[list[StockMatch], list[BrokerageMatch]]:
        return resolve_entities(self.tagger.find(text), self.brokers.find(text))

    def _single_stock_unit(self, text: str) -> str | None:
        """The clause naming the stock, plus directly following price-detail clauses.
        Other clauses of roundup headlines ("X on A; Y on B") are never mixed in."""
        clauses = [c for c in _CLAUSE_SPLIT.split(text) if c]
        if len(clauses) <= 1:
            return text
        for i, clause in enumerate(clauses):
            if self._entities(clause)[0]:
                parts = [clause]
                for follow in clauses[i + 1:]:
                    if not _CONTINUATION.match(follow):
                        break
                    parts.append(follow)
                return "; ".join(parts)
        return None

    def _find_action(self, unit: str, stock: StockMatch) -> tuple[str, str] | None:
        """Returns (original wording, context) for the first rating found in an accepted context."""
        m = self._imperative.match(unit)
        if m and 0 <= stock.start - m.end() <= 3:
            return m.group("a"), "imperative"
        best: tuple[int, str, str] | None = None
        for ctx, rx in self._contexts:
            for m in rx.finditer(unit):
                start = m.start("a")
                if ctx in ("quoted", "suffix", "verb") and _BAD_PREFIX.search(unit[: m.start()]):
                    continue
                if _BAD_SUFFIX.match(unit[m.end("a"):].lstrip("'\"’”")):
                    continue
                if best is None or start < best[0]:
                    best = (start, m.group("a"), ctx)
                break
        return (best[1], best[2]) if best else None

    def _from_unit(self, unit: str, stocks: list[StockMatch], brokers: list[BrokerageMatch],
                   allow_trailing_attribution: bool, require_attribution: bool = False) -> ExtractedRec | None:
        stock = stocks[0]
        found = self._find_action(unit, stock)
        if not found:
            return None
        original, ctx = found
        original = original.strip("'\"‘’“” ")
        normalized = self.normalizer.action(original)

        brokerage, analyst = self._attribution(unit, brokers, allow_trailing_attribution and ctx == "imperative")
        target, target_text = _find_price(_TARGET_RX, unit)
        stop_loss, _ = _find_price(_SL_RX, unit)
        cmp_price, _ = _find_price(_CMP_RX, unit)
        horizon_original, horizon = self.normalizer.horizon(unit)

        if require_attribution and not (brokerage or analyst):
            return None
        if not (brokerage or analyst or target):
            return None  # an unattributed rating word with no target is too weak to record

        confidence = 0.5 + (0.2 if (brokerage or analyst) else 0) + (0.15 if target else 0) + \
            (0.1 if ctx in ("imperative", "quoted", "change") else 0)
        return ExtractedRec(
            stock_id=stock.stock_id, symbol=stock.symbol, original_action=original.title() if original.islower() else original,
            normalized_action=normalized, rating_change=self._rating_change(unit), brokerage=brokerage, analyst=analyst,
            target_price=target, target_text=target_text, stop_loss=stop_loss, price_at_reco=cmp_price,
            horizon_original=horizon_original, horizon=horizon, evidence_text=unit.strip(),
            confidence=round(min(confidence, 0.95), 2), brokerage_spans=brokers,
        )

    @staticmethod
    def _rating_change(unit: str) -> str:
        for label, rx in _CHANGE_RX:
            if rx.search(unit):
                return label
        return "N/A"

    def _attribution(self, unit: str, brokers: list[BrokerageMatch], trailing: bool) -> tuple[str | None, str | None]:
        brokerage = analyst = None
        if brokers:
            brokerage = brokers[0].name
            b = brokers[0]
            before = re.search(rf"({_NAME})\s+(?:of|from|at)\s+$", unit[: b.start])
            after = re.match(rf"^['’]s?\s+({_NAME})", unit[b.end:])
            candidate = (before or after).group(1) if (before or after) else None
            if candidate and self._plausible_person(candidate):
                analyst = candidate
        if trailing and ":" in unit:
            segment = unit.rsplit(":", 1)[1].strip()
            if brokerage is None and segment and len(segment) <= 80:
                person = re.fullmatch(rf"({_NAME})(?:\s+(?:of|from|at)\s+(.+))?", segment)
                if person and not _CORP_WORDS.search(person.group(1)) and self._plausible_person(person.group(1)):
                    analyst = person.group(1)
                    brokerage = person.group(2).strip() if person.group(2) else None
                elif _CORP_WORDS.search(segment) and not re.search(r"\d", segment):
                    brokerage = segment
        return brokerage, analyst

    def _plausible_person(self, name: str) -> bool:
        words = name.split()
        if not 2 <= len(words) <= 4:
            return False
        if any(w.lower().strip(".'’") in _NAME_STOPWORDS for w in words):
            return False
        if self.tagger.find(name) or self.brokers.find(name):
            return False
        return self.normalizer.action(words[0]) == "UNMAPPED"

    def _supplement_from_snippet(self, rec: ExtractedRec, snippet: str | None) -> None:
        """Fill missing details from the publisher's snippet only when it concerns the same single stock."""
        if not snippet:
            return
        stocks, brokers = resolve_entities(self.tagger.find(snippet), self.brokers.find(snippet))
        if {s.stock_id for s in stocks} - {rec.stock_id}:
            return
        used = False
        if rec.target_price is None:
            rec.target_price, rec.target_text = _find_price(_TARGET_RX, snippet)
            used |= rec.target_price is not None
        if rec.stop_loss is None:
            rec.stop_loss, _ = _find_price(_SL_RX, snippet)
            used |= rec.stop_loss is not None
        if rec.price_at_reco is None:
            rec.price_at_reco, _ = _find_price(_CMP_RX, snippet)
            used |= rec.price_at_reco is not None
        if rec.horizon is None:
            rec.horizon_original, rec.horizon = self.normalizer.horizon(snippet)
            used |= rec.horizon is not None
        if rec.brokerage is None and len({b.name for b in brokers}) == 1:
            rec.brokerage = brokers[0].name
            used = True
        if used:
            rec.evidence_text = f"{rec.evidence_text} || {snippet}"

    def _from_snippet(self, snippet: str) -> list[ExtractedRec]:
        out = []
        for sentence in re.split(r"(?<=[.!?;])\s+", snippet):
            stocks, brokers = resolve_entities(self.tagger.find(sentence), self.brokers.find(sentence))
            if len({s.stock_id for s in stocks}) != 1 or not brokers:
                continue
            rec = self._from_unit(sentence, stocks, brokers, allow_trailing_attribution=False, require_attribution=True)
            if rec:
                rec.confidence = round(rec.confidence - 0.1, 2)
                out.append(rec)
        return out

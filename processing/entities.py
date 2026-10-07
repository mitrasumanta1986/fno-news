"""Finds F&O stocks and brokerages mentioned in text.

Precision matters more than recall: an article wrongly tagged to a stock is worse than a missed
tag. Aliases shared by more than one stock are dropped, short/upper-case aliases are matched
case-sensitively, and overlapping stock/brokerage names (e.g. "Kotak" vs "Kotak Bank") resolve
to the longer match.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

LEGAL_SUFFIX = re.compile(r"[\s,]*\b(?:limited|ltd\.?)\s*$", re.I)
GENERIC_ALIASES = {
    "india", "bank", "power", "finance", "capital", "energy", "industries", "global", "national",
    "life", "gas", "steel", "motors", "one", "the", "housing", "infra", "labs", "systems",
}
STOP_SYMBOLS = {
    "IT", "NSE", "BSE", "IPO", "GST", "RBI", "CEO", "CFO", "FII", "DII", "FPI", "USA", "GDP", "EV", "AI",
    "US", "UK", "PSU", "NBFC", "SEBI", "OFS", "QIP", "MD", "EPS", "PAT", "AGM", "EGM", "LTD", "CMP", "TP",
}
_APOS = "['’]"
# "Mahindra and Mahindra" followed by "Financial Services" is a different company. If the longer
# name were an F&O alias it would already have won (longest match first), so drop the match.
_SUFFIX_GUARD = re.compile(
    r"^\s+(?:financial|finance|fin|finserv|life|securities|capital|amc|asset|insurance|housing|ventures|holdings|"
    r"credit|general|ports?|green|energy|gas|motors?|passenger|commercial|renewables?|realty|chemicals|"
    r"investments?|lombard|prudential|technologies|consumer|pharma)\b", re.I)


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip().lower()


def _alias_regex(alias: str) -> str:
    parts = []
    for ch in alias:
        if ch.isspace():
            if not parts or parts[-1] != r"\s+":
                parts.append(r"\s+")
        elif ch in "'’":
            parts.append(_APOS)
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _is_case_sensitive(alias: str) -> bool:
    letters = [c for c in alias if c.isalpha()]
    return bool(letters) and alias.upper() == alias and len(alias) <= 8 or " " not in alias.strip()


def _compile(aliases: Iterable[str], case_sensitive: bool) -> re.Pattern | None:
    ordered = sorted(set(aliases), key=len, reverse=True)
    if not ordered:
        return None
    body = "|".join(_alias_regex(a) for a in ordered)
    return re.compile(rf"(?<![\w&])(?:{body})(?![\w&])", 0 if case_sensitive else re.I)


@dataclass(frozen=True)
class StockMatch:
    stock_id: int
    symbol: str
    start: int
    end: int
    alias: str
    kind: str


@dataclass(frozen=True)
class BrokerageMatch:
    name: str
    start: int
    end: int
    alias: str


def derive_name_aliases(name: str) -> list[str]:
    base = LEGAL_SUFFIX.sub("", name).strip().rstrip(",.").strip()
    variants = {base}
    if "&" in base:
        variants.add(re.sub(r"\s*&\s*", " and ", base))
    if re.search(r"\band\b", base, re.I):
        variants.add(re.sub(r"\s+and\s+", " & ", base, flags=re.I))
    return [v for v in variants if len(v) >= 3 and v.lower() not in GENERIC_ALIASES]


def build_alias_map(stocks: Iterable[tuple[int, str, str]], curated: dict[str, list[str]]) -> dict[int, list[tuple[str, str]]]:
    """stocks: (stock_id, symbol, name). Returns stock_id -> [(alias, kind)] with ambiguous aliases removed."""
    candidates: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for stock_id, symbol, name in stocks:
        for alias in derive_name_aliases(name):
            candidates[stock_id].append((alias, "NAME"))
        for alias in curated.get(symbol, []):
            candidates[stock_id].append((str(alias), "CURATED"))
        if len(symbol) >= 3 and symbol.upper() not in STOP_SYMBOLS and re.fullmatch(r"[A-Z&-]+", symbol):
            candidates[stock_id].append((symbol, "SYMBOL"))

    owners: dict[str, set[int]] = defaultdict(set)
    curated_owners: dict[str, set[int]] = defaultdict(set)
    for stock_id, items in candidates.items():
        for alias, kind in items:
            owners[_norm_key(alias)].add(stock_id)
            if kind == "CURATED":
                curated_owners[_norm_key(alias)].add(stock_id)

    result: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for stock_id, items in candidates.items():
        seen = set()
        for alias, kind in items:
            key = _norm_key(alias)
            if key in seen:
                continue
            ids = owners[key]
            if len(ids) > 1 and curated_owners.get(key) != {stock_id}:
                continue  # ambiguous alias: skip rather than guess
            seen.add(key)
            result[stock_id].append((alias, kind))
    return dict(result)


class StockTagger:
    def __init__(self, alias_rows: Iterable[tuple[int, str, str, str]]):
        self._sensitive: dict[str, tuple[int, str, str]] = {}
        self._insensitive: dict[str, tuple[int, str, str]] = {}
        for stock_id, symbol, alias, kind in alias_rows:
            if kind == "SYMBOL" or (alias.upper() == alias and len(alias) <= 8):
                self._sensitive[alias.replace("’", "'")] = (stock_id, symbol, kind)
            else:
                self._insensitive[_norm_key(alias)] = (stock_id, symbol, kind)
        self._rx_sensitive = _compile(self._sensitive, True)
        self._rx_insensitive = _compile(self._insensitive, False)

    def find(self, text: str) -> list[StockMatch]:
        found: list[StockMatch] = []
        if self._rx_insensitive:
            for m in self._rx_insensitive.finditer(text):
                sid, sym, kind = self._insensitive[_norm_key(m.group(0))]
                found.append(StockMatch(sid, sym, m.start(), m.end(), m.group(0), kind))
        if self._rx_sensitive:
            for m in self._rx_sensitive.finditer(text):
                sid, sym, kind = self._sensitive[m.group(0).replace("’", "'")]
                found.append(StockMatch(sid, sym, m.start(), m.end(), m.group(0), kind))
        found = [m for m in found if not _SUFFIX_GUARD.match(text[m.end:m.end + 40])]
        return _drop_overlaps(found)


class BrokerageMatcher:
    def __init__(self, brokerages: dict[str, list[str]]):
        self._sensitive: dict[str, str] = {}
        self._insensitive: dict[str, str] = {}
        for canonical, aliases in brokerages.items():
            for alias in [canonical, *aliases]:
                alias = str(alias)
                if " " not in alias.strip() or alias.isupper():
                    self._sensitive[alias.replace("’", "'")] = canonical
                else:
                    self._insensitive[_norm_key(alias)] = canonical
        self._rx_sensitive = _compile(self._sensitive, True)
        self._rx_insensitive = _compile(self._insensitive, False)

    def find(self, text: str) -> list[BrokerageMatch]:
        found = []
        if self._rx_insensitive:
            for m in self._rx_insensitive.finditer(text):
                found.append(BrokerageMatch(self._insensitive[_norm_key(m.group(0))], m.start(), m.end(), m.group(0)))
        if self._rx_sensitive:
            for m in self._rx_sensitive.finditer(text):
                found.append(BrokerageMatch(self._sensitive[m.group(0).replace("’", "'")], m.start(), m.end(), m.group(0)))
        return _drop_overlaps(found)


def _drop_overlaps(matches: list) -> list:
    kept: list = []
    for m in sorted(matches, key=lambda x: (-(x.end - x.start), x.start)):
        if all(m.end <= k.start or m.start >= k.end for k in kept):
            kept.append(m)
    return sorted(kept, key=lambda x: x.start)


def resolve_entities(stocks: list[StockMatch], brokers: list[BrokerageMatch]) -> tuple[list[StockMatch], list[BrokerageMatch]]:
    """Resolve text spans claimed by both a stock alias and a brokerage alias."""
    drop_stock: set[int] = set()
    drop_broker: set[int] = set()
    equal: list[tuple[int, int]] = []
    for si, s in enumerate(stocks):
        for bi, b in enumerate(brokers):
            if s.end <= b.start or s.start >= b.end:
                continue
            s_len, b_len = s.end - s.start, b.end - b.start
            if b_len > s_len:
                drop_stock.add(si)       # "Kotak" (stock alias) inside "Kotak Institutional Equities"
            elif s_len > b_len:
                drop_broker.add(bi)      # "Kotak" (brokerage) inside "Kotak Mahindra Bank"
            else:
                equal.append((si, bi))   # e.g. "Angel One": stock and brokerage share the name
    for si, bi in equal:
        other_stocks = [i for i in range(len(stocks)) if i != si and i not in drop_stock and stocks[i].stock_id != stocks[si].stock_id]
        if other_stocks:
            drop_stock.add(si)
        else:
            drop_broker.add(bi)
    return ([s for i, s in enumerate(stocks) if i not in drop_stock],
            [b for i, b in enumerate(brokers) if i not in drop_broker])

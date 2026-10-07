"""Maps published rating wording and horizons to normalized values (rules in config/normalization.yaml)."""
from __future__ import annotations

import re
from typing import Any

NORMALIZED_ACTIONS = ("BUY", "ACCUMULATE", "HOLD", "NEUTRAL", "REDUCE", "SELL")
UNMAPPED = "UNMAPPED"


def _key(term: str) -> str:
    return re.sub(r"[\s\-]+", " ", term.strip().lower().strip("'\"‘’“”"))


def term_pattern(term: str) -> str:
    """'market perform' also matches 'market-perform'; 'equal-weight' matches 'equal weight'."""
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
    return r"[\s\-]*".join(parts)


class Normalizer:
    def __init__(self, config: dict[str, Any]):
        self._action_map: dict[str, str] = {}
        for action, terms in (config.get("actions") or {}).items():
            for term in terms:
                self._action_map[_key(term)] = action
        self.weak_terms = {_key(t) for t in config.get("weak_terms") or []}
        self._horizons: list[tuple[str, str]] = []
        for horizon, phrases in (config.get("horizons") or {}).items():
            for phrase in phrases:
                self._horizons.append((phrase, horizon))
        self._horizons.sort(key=lambda x: len(x[0]), reverse=True)
        self._horizon_rx = [
            (re.compile(rf"(?<![\w-]){term_pattern(p)}(?![\w-])", re.I), h) for p, h in self._horizons
        ]

    @property
    def all_terms(self) -> list[str]:
        return sorted(self._action_map, key=len, reverse=True)

    @property
    def strong_terms(self) -> list[str]:
        return [t for t in self.all_terms if t not in self.weak_terms]

    def action(self, original: str) -> str:
        return self._action_map.get(_key(original), UNMAPPED)

    def horizon(self, text: str) -> tuple[str | None, str | None]:
        """Returns (original phrase as published, normalized) or (None, None). Never inferred."""
        if not text:
            return None, None
        for rx, horizon in self._horizon_rx:
            m = rx.search(text)
            if m:
                return m.group(0), horizon
        return None, None

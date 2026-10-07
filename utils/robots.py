"""robots.txt evaluation following RFC 9309 (wildcards, '$' anchors, longest match wins).

Python's urllib.robotparser does not implement wildcards or longest-match precedence and
mis-evaluates several Indian news sites' robots files, so we use this implementation instead.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


def parse_robots(text: str) -> list[_Group]:
    groups: list[_Group] = []
    current: _Group | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key in ("allow", "disallow") and current is not None:
            if key == "disallow" and not value:
                continue  # "Disallow:" (empty) allows everything
            current.rules.append((key == "allow", value))
    return groups


def _pattern_matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.match(regex + ("$" if anchored else ""), path) is not None


class RobotsRules:
    def __init__(self, groups: list[_Group] | None = None, allow_all: bool = False, disallow_all: bool = False):
        self.groups = groups or []
        self.allow_all = allow_all
        self.disallow_all = disallow_all

    @classmethod
    def from_text(cls, text: str) -> "RobotsRules":
        return cls(parse_robots(text))

    def _rules_for(self, agent_token: str) -> list[tuple[bool, str]]:
        token = agent_token.lower()
        specific = [g for g in self.groups if any(a != "*" and a and a in token for a in g.agents)]
        chosen = specific or [g for g in self.groups if "*" in g.agents]
        return [rule for g in chosen for rule in g.rules]

    def can_fetch(self, agent_token: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: tuple[int, bool] | None = None
        for allow, pattern in self._rules_for(agent_token):
            if not pattern or not _pattern_matches(pattern, path):
                continue
            candidate = (len(pattern), allow)
            # Longest match wins; on equal length, allow wins.
            if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and allow):
                best = candidate
        return True if best is None else best[1]


class RobotsCache:
    """Fetches and caches robots.txt per host.

    fetcher(url) must return (status_code, text) or raise on network failure.
    """

    def __init__(self, fetcher: Callable[[str], tuple[int, str]], ttl_seconds: int = 24 * 3600):
        self._fetcher = fetcher
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[RobotsRules, float]] = {}
        self._lock = threading.Lock()

    def rules_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            cached = self._cache.get(origin)
            if cached and cached[1] > time.time():
                return cached[0]
        ttl = self._ttl
        try:
            status, text = self._fetcher(origin + "/robots.txt")
            if status == 200:
                rules = RobotsRules.from_text(text)
            elif status in (401, 403):
                # The server refuses automated clients outright; treat as full disallow.
                rules = RobotsRules(disallow_all=True)
            elif 400 <= status < 500:
                rules = RobotsRules(allow_all=True)  # no robots.txt => no restrictions
            else:
                rules, ttl = RobotsRules(disallow_all=True), 3600
        except Exception as exc:  # network failure: be conservative, retry in an hour
            log.warning("robots.txt fetch failed for %s: %s", origin, exc)
            rules, ttl = RobotsRules(disallow_all=True), 3600
        with self._lock:
            self._cache[origin] = (rules, time.time() + ttl)
        return rules

    def can_fetch(self, agent_token: str, url: str) -> bool:
        return self.rules_for(url).can_fetch(agent_token, url)

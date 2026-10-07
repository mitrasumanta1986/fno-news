"""Story clustering: the same story from several outlets shares one story_cluster_id."""
from __future__ import annotations

from rapidfuzz import fuzz, process

from utils.hashing import normalize_headline

FUZZY_THRESHOLD = 90


class ClusterIndex:
    def __init__(self, rows: list[tuple[int, str, str, int | None]]):
        """rows: (news_id, headline, content_hash, cluster_id) for recent news."""
        self._by_hash: dict[str, int] = {}
        self._norm: list[str] = []
        self._clusters: list[int] = []
        for news_id, headline, chash, cluster in rows:
            self.add(cluster or news_id, headline, chash)

    def find(self, headline: str, chash: str) -> int | None:
        if chash in self._by_hash:
            return self._by_hash[chash]
        if not self._norm:
            return None
        best = process.extractOne(normalize_headline(headline), self._norm, scorer=fuzz.token_sort_ratio,
                                  score_cutoff=FUZZY_THRESHOLD)
        return self._clusters[best[2]] if best else None

    def add(self, cluster_id: int, headline: str, chash: str) -> None:
        self._by_hash.setdefault(chash, cluster_id)
        self._norm.append(normalize_headline(headline))
        self._clusters.append(cluster_id)

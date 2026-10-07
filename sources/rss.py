"""Generic RSS/Atom source. Keeps headline, publisher-provided description, date and link."""
from __future__ import annotations

import logging

import feedparser

from sources.base import BaseSource, FetchOutcome, RawItem
from utils.http import BlockedError, FetchError, RateLimitedError, RobotsDisallowedError
from utils.timeutils import parse_datetime

log = logging.getLogger(__name__)


class RssSource(BaseSource):
    def fetch(self) -> FetchOutcome:
        items: list[RawItem] = []
        errors: list[str] = []
        not_modified = 0
        for url in self.config.feeds:
            try:
                resp = self.client.get(url, conditional=True)
            except (RateLimitedError, BlockedError, RobotsDisallowedError):
                raise  # these describe the whole source
            except FetchError as exc:
                errors.append(str(exc))
                log.warning("[%s] feed failed: %s", self.config.name, exc)
                continue
            if resp.not_modified:
                not_modified += 1
                continue
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                errors.append(f"unparseable feed {url}: {parsed.get('bozo_exception')}")
                continue
            items.extend(self.parse_entries(parsed.entries))
        if errors and not items and not_modified == 0:
            raise FetchError("; ".join(errors))
        return FetchOutcome(items=items, not_modified=not_modified == len(self.config.feeds), feed_errors=errors)

    def parse_entries(self, entries) -> list[RawItem]:
        out = []
        for e in entries:
            title, link = e.get("title"), e.get("link")
            if not title or not link:
                continue
            published = parse_datetime(e.get("published_parsed") or e.get("updated_parsed")) or \
                parse_datetime(e.get("published") or e.get("updated"))
            out.append(RawItem(title=title, url=link, publisher=self.config.publisher,
                               summary=e.get("summary"), published=published))
        return out

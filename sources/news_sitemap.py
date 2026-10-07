"""Google-News-format sitemap source (publisher-declared in robots.txt).
Provides URL, headline and publication time only."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta

from sources.base import BaseSource, FetchOutcome, RawItem
from utils.http import BlockedError, FetchError, RateLimitedError, RobotsDisallowedError
from utils.timeutils import now_utc, parse_datetime

log = logging.getLogger(__name__)

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9", "news": "http://www.google.com/schemas/sitemap-news/0.9"}


def parse_news_sitemap(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for url_el in root.findall("sm:url", NS):
        loc = url_el.findtext("sm:loc", default="", namespaces=NS).strip()
        news_el = url_el.find("news:news", NS)
        if not loc or news_el is None:
            continue
        out.append({
            "url": loc,
            "title": (news_el.findtext("news:title", default="", namespaces=NS) or "").strip(),
            "published": news_el.findtext("news:publication_date", default=None, namespaces=NS),
        })
    return out


class NewsSitemapSource(BaseSource):
    def fetch(self) -> FetchOutcome:
        include = self.config.options.get("include_url_patterns") or []
        max_age = timedelta(hours=float(self.config.options.get("max_age_hours", 72)))
        cutoff = now_utc() - max_age
        items: list[RawItem] = []
        errors: list[str] = []
        for url in self.config.feeds:
            try:
                resp = self.client.get(url, conditional=True)
            except (RateLimitedError, BlockedError, RobotsDisallowedError):
                raise
            except FetchError as exc:
                errors.append(str(exc))
                continue
            if resp.not_modified:
                continue
            try:
                entries = parse_news_sitemap(resp.content)
            except ET.ParseError as exc:
                errors.append(f"unparseable sitemap {url}: {exc}")
                continue
            for e in entries:
                if include and not any(p in e["url"] for p in include):
                    continue
                published = parse_datetime(e["published"])
                if published and published < cutoff:
                    continue
                if e["title"]:
                    items.append(RawItem(title=e["title"], url=e["url"], publisher=self.config.publisher,
                                         published=published))
        if errors and not items:
            raise FetchError("; ".join(errors))
        return FetchOutcome(items=items, feed_errors=errors)

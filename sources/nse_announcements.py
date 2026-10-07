"""NSE corporate announcements RSS (official exchange disclosures)."""
from __future__ import annotations

import re

from sources.base import RawItem
from sources.rss import RssSource
from utils.timeutils import IST, parse_datetime


class NseAnnouncementsSource(RssSource):
    def parse_entries(self, entries) -> list[RawItem]:
        ignore = [s.lower() for s in self.config.options.get("ignore_subjects", [])]
        out = []
        for e in entries:
            company = (e.get("title") or "").strip()
            link = e.get("link")
            summary = (e.get("summary") or "").strip()
            if not company or not link:
                continue
            match = re.search(r"\|\s*SUBJECT\s*:\s*(.+)$", summary, flags=re.I)
            subject = match.group(1).strip() if match else ""
            body = summary[: match.start()].strip() if match else summary
            if any(term in (subject + " " + body).lower() for term in ignore):
                continue
            headline = f"{company}: {subject}" if subject else company
            out.append(RawItem(
                title=headline, url=link, publisher="NSE", summary=body,
                published=parse_datetime(e.get("published"), assume_tz=IST),
                extra={"company": company, "subject": subject},
            ))
        return out

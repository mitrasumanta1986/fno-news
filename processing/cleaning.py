"""Text cleanup for headlines and publisher-provided snippets."""
from __future__ import annotations

import html
import re
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = value
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = html.unescape(text).replace("]]>", "").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_headline(value: str | None) -> str:
    return clean_text(value).strip(" -|")


def truncate(text: str | None, max_chars: int) -> str | None:
    """Snippets are capped (copyright: we keep only a short excerpt, never article bodies)."""
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"

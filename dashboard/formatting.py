"""Display helpers. Missing values are always shown as N/A (never guessed)."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

import pandas as pd

from utils.timeutils import fmt_ist

NA = "N/A"


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA or value == ""


def na(value) -> str:
    return NA if _missing(value) else str(value)


def price(value) -> str:
    return NA if _missing(value) else f"₹{float(value):,.2f}"


def crore(value) -> str:
    return NA if _missing(value) else f"₹{float(value) / 1e7:,.2f} cr"


def pct(value) -> str:
    return NA if _missing(value) else f"{float(value):+.2f}%"


def ist(iso_value, with_time: bool = True) -> str:
    if _missing(iso_value):
        return NA
    return fmt_ist(iso_value, "%d %b %Y %H:%M" if with_time else "%d %b %Y")


def safe_url(url) -> str | None:
    """Only http(s) links are ever rendered."""
    if _missing(url):
        return None
    return url if urlsplit(str(url)).scheme in ("http", "https") else None


def upside(target, close) -> float | None:
    if _missing(target) or _missing(close) or not close:
        return None
    return (float(target) - float(close)) / float(close) * 100


ACTION_ICONS = {"BUY": "🟢", "ACCUMULATE": "🟩", "HOLD": "🟡", "NEUTRAL": "⚪", "REDUCE": "🟧", "SELL": "🔴", "UNMAPPED": "❔"}


def action_label(normalized, original=None) -> str:
    if _missing(normalized):
        return NA
    icon = ACTION_ICONS.get(str(normalized), "")
    if original and str(original).strip().upper() != str(normalized):
        return f"{icon} {normalized} ({original})"
    return f"{icon} {normalized}"

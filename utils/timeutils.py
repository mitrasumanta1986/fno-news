"""Time helpers. Timestamps are stored as UTC ISO-8601 strings and displayed in IST."""
from __future__ import annotations

import calendar
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

_EXTRA_FORMATS = (
    "%d-%b-%Y %H:%M:%S",  # NSE RSS: 28-Sep-2026 10:11:55
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y",
    "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def now_iso() -> str:
    return to_iso(now_utc())  # type: ignore[return-value]


def parse_datetime(value: object, assume_tz=IST) -> datetime | None:
    """Parse the many date formats feeds use. Naive values are assumed to be IST."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=assume_tz)
    if isinstance(value, time.struct_time):
        # feedparser's *_parsed values are already normalized to UTC
        return datetime.fromtimestamp(calendar.timegm(value), UTC)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=assume_tz)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=assume_tz)
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in _EXTRA_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=assume_tz)
        except ValueError:
            continue
    return None


def iso_to_ist(iso_value: str | None) -> datetime | None:
    if not iso_value:
        return None
    dt = parse_datetime(iso_value, assume_tz=UTC)
    return dt.astimezone(IST) if dt else None


def fmt_ist(iso_value: str | None, fmt: str = "%d %b %Y %H:%M") -> str:
    dt = iso_to_ist(iso_value)
    return dt.strftime(fmt) + (" IST" if "%H" in fmt else "") if dt else "N/A"


def is_market_hours(dt: datetime | None = None) -> bool:
    """Broad 'active news' window: Mon-Fri 08:00-16:00 IST."""
    dt = (dt or now_utc()).astimezone(IST)
    return dt.weekday() < 5 and 8 <= dt.hour < 16

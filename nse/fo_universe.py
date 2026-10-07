"""Dynamic NSE F&O stock universe.

Primary source: NSE's published F&O market-lot file (lists every derivative underlying).
Fallbacks, in order: the last successfully downloaded copy in data/cache, then a copy the
user drops into data/manual/fo_mktlots.csv.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

from config.settings import Settings
from database.repository import FoEntry, Repository
from utils.http import HttpClient
from utils.timeutils import today_ist

log = logging.getLogger(__name__)

FO_LOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
MIN_PLAUSIBLE_STOCKS = 50  # guard: a truncated/garbled file must never deactivate the universe


def parse_fo_mktlots(text: str) -> list[FoEntry]:
    entries: dict[str, FoEntry] = {}
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if len(cells) < 2:
            continue
        underlying, symbol = cells[0], cells[1]
        if not symbol or symbol.upper() == "SYMBOL" or underlying.lower().startswith("derivatives on"):
            continue
        if symbol.upper() in INDEX_UNDERLYINGS or underlying.upper().startswith("NIFTY"):
            continue
        lot = next((int(c) for c in cells[2:] if re.fullmatch(r"\d+", c)), None)
        entries[symbol.upper()] = FoEntry(symbol=symbol.upper(), underlying=_clean_name(underlying), lot_size=lot)
    return list(entries.values())


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name.isupper() else name


def _load_text(client: HttpClient, settings: Settings) -> tuple[str, str]:
    cache_file = settings.cache_dir / "fo_mktlots.csv"
    manual_file = settings.manual_dir / "fo_mktlots.csv"
    try:
        resp = client.get(FO_LOTS_URL)
        text = resp.text
        if len(parse_fo_mktlots(text)) >= MIN_PLAUSIBLE_STOCKS:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
            return text, "NSE (live)"
        log.warning("F&O list from NSE looked implausible; falling back")
    except Exception as exc:
        log.warning("F&O list download failed: %s", exc)
    for path, label in ((manual_file, "manual file"), (cache_file, "cached copy")):
        if Path(path).exists():
            return Path(path).read_text(encoding="utf-8", errors="replace"), label
    raise RuntimeError("F&O list unavailable: NSE download failed and no cached/manual copy exists")


def refresh_universe(repo: Repository, client: HttpClient, settings: Settings) -> dict:
    text, origin = _load_text(client, settings)
    entries = parse_fo_mktlots(text)
    if len(entries) < MIN_PLAUSIBLE_STOCKS:
        raise RuntimeError(f"F&O list from {origin} has only {len(entries)} stocks; refusing to apply")
    result = repo.apply_fo_universe(entries, today_ist())
    result["origin"] = origin
    log.info("F&O universe: %s stocks (%s); added=%s removed=%s",
             result["total"], origin, result["added"], result["removed"])
    return result

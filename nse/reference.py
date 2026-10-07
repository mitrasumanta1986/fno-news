"""Company names, sectors and ISINs from NSE's published index-constituent files.
Stocks absent from these lists keep sector = NULL (shown as N/A)."""
from __future__ import annotations

import csv
import io
import logging

from utils.http import HttpClient

log = logging.getLogger(__name__)

INDEX_LIST_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
]


def parse_index_list(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        symbol = row.get("Symbol", "").upper()
        if not symbol:
            continue
        out[symbol] = {
            "name": row.get("Company Name") or None,
            "sector": row.get("Industry") or None,
            "isin": row.get("ISIN Code") or None,
        }
    return out


def fetch_reference_data(client: HttpClient) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for url in INDEX_LIST_URLS:
        try:
            data = parse_index_list(client.get(url).text)
            for symbol, info in data.items():
                merged.setdefault(symbol, info)
        except Exception as exc:
            log.warning("reference list %s unavailable: %s", url, exc)
    return merged

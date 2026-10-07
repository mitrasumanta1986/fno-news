"""Live index levels from NSE's own market-watch feed (the data behind the website's "All Indices"
download). Official values: last, previous close, % change, day high/low. Yahoo bars are only a fallback.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from database.repository import Repository
from utils.http import HttpClient
from utils.timeutils import IST, now_iso, to_iso

log = logging.getLogger(__name__)

ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
SOURCE = "NSE live (allIndices)"


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_all_indices(payload: dict, known_names: list[str]) -> list[dict]:
    """NSE upper-cases names ("NIFTY 50"); map them back to the closing file's names ("Nifty 50")."""
    canonical = {n.upper(): n for n in known_names}
    stamp = datetime.strptime(payload["timestamp"], "%d-%b-%Y %H:%M").replace(tzinfo=IST)
    rows = []
    for x in payload.get("data", []):
        name, last, prev = (x.get("index") or "").strip(), _num(x.get("last")), _num(x.get("previousClose"))
        if not name or last is None:
            continue
        rows.append({
            "index_name": canonical.get(name.upper(), name), "session_date": stamp.date().isoformat(),
            "bar_time": to_iso(stamp), "last": last, "prev_close": prev,
            "change_pct": _num(x.get("percentChange")), "day_high": _num(x.get("high")), "day_low": _num(x.get("low")),
            "computed_at": now_iso(), "source": SOURCE,
        })
    return rows


def refresh_live_indices(repo: Repository, client: HttpClient) -> dict:
    payload = json.loads(client.get(ALL_INDICES_URL).text)
    names = [r[0] for r in repo.conn.execute("SELECT DISTINCT index_name FROM index_levels")]
    rows = parse_all_indices(payload, names)
    repo.upsert_intraday_index(rows)
    log.info("NSE live indices: %s rows as of %s", len(rows), payload.get("timestamp"))
    return {"nse_live_indices": len(rows), "nse_live_as_of": payload.get("timestamp")}

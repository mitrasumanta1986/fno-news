"""Stock-derivative activity from NSE's official F&O bhavcopy (UDiFF, EOD):
open interest, traded contracts and notional turnover aggregated per underlying."""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections import defaultdict
from datetime import timedelta

from database.repository import Repository
from nse.prices import _num
from utils.http import FetchError, HttpClient
from utils.timeutils import now_ist

log = logging.getLogger(__name__)

FO_BHAV_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
STOCK_FUT, STOCK_OPT = "STF", "STO"


def parse_fo_bhavcopy(zip_bytes: bytes, symbol_ids: dict[str, int]) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    agg: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    meta: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        kind = (r.get("FinInstrmTp") or "").strip()
        symbol = (r.get("TckrSymb") or "").strip().upper()
        if kind not in (STOCK_FUT, STOCK_OPT) or symbol not in symbol_ids:
            continue
        a = agg[symbol]
        oi = _num(r.get("OpnIntrst")) or 0.0
        prefix = "fut" if kind == STOCK_FUT else "opt"
        a[f"{prefix}_oi"] += oi
        a["oi_change"] += _num(r.get("ChngInOpnIntrst")) or 0.0
        a[f"{prefix}_contracts"] += _num(r.get("TtlTradgVol")) or 0.0
        a["turnover"] += _num(r.get("TtlTrfVal")) or 0.0
        lot = _num(r.get("NewBrdLotQty"))
        m = meta.setdefault(symbol, {"trade_date": (r.get("TradDt") or "").strip()})
        if lot and not m.get("lot_size"):
            m["lot_size"] = int(lot)
        if kind == STOCK_FUT and _num(r.get("UndrlygPric")):
            m["underlying_price"] = _num(r.get("UndrlygPric"))
        m.setdefault("underlying_price", _num(r.get("UndrlygPric")))
    rows = []
    for symbol, a in agg.items():
        m = meta[symbol]
        total_oi = a["fut_oi"] + a["opt_oi"]
        lot = m.get("lot_size")
        rows.append({
            "stock_id": symbol_ids[symbol], "trade_date": m["trade_date"],
            "fut_oi": a["fut_oi"], "opt_oi": a["opt_oi"], "total_oi": total_oi,
            "oi_contracts": total_oi / lot if lot else None, "oi_change": a["oi_change"],
            "fut_contracts": a["fut_contracts"], "opt_contracts": a["opt_contracts"],
            "total_contracts": a["fut_contracts"] + a["opt_contracts"], "turnover": a["turnover"],
            "underlying_price": m.get("underlying_price"), "lot_size": lot, "source": "NSE F&O bhavcopy (EOD)",
        })
    return rows


def refresh_fo_activity(repo: Repository, client: HttpClient, lookback_days: int = 7) -> dict:
    symbol_ids = {r["symbol"]: r["id"] for r in repo.active_stocks()}
    have = {r[0] for r in repo.conn.execute("SELECT DISTINCT trade_date FROM fo_activity")}
    now = now_ist()
    start = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    loaded = []
    for i in range(lookback_days):
        d = start - timedelta(days=i)
        if d.weekday() >= 5 or d.isoformat() in have:
            continue
        try:
            rows = parse_fo_bhavcopy(client.get(FO_BHAV_URL.format(d=d)).content, symbol_ids)
        except FetchError as exc:
            if exc.status != 404:
                log.warning("F&O bhavcopy %s failed: %s", d, exc)
            continue
        if rows:
            repo.upsert_fo_activity(rows)
            loaded.append(d.isoformat())
            if len(have) + len(loaded) >= 2:
                break  # latest day (and a prior day for context) is enough
    log.info("F&O activity loaded for %s", loaded)
    return {"fo_days_loaded": loaded}

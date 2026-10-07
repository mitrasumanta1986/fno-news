"""Hourly market analysis snapshot (09:00-16:00 IST).

Every statement is a rule-generated FACT derived from stored data (index moves, breadth, sectors,
volatility, technical-setup counts, news flow, published research, F&O activity). There is no
forecast and no buy/sell call. An optional AI narrative (AI_ENABLED) is stored separately and
labelled "AI SUMMARY" in the UI.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from config.settings import Settings
from database.repository import Repository
from utils.timeutils import now_iso, today_ist

log = logging.getLogger(__name__)
KEY_INDICES = ["Nifty 50", "Nifty Bank", "Nifty Financial Services", "Nifty IT", "Nifty Auto", "Nifty Pharma",
               "Nifty Metal", "India VIX"]


def _df(repo: Repository, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, repo.conn, params=params)


def _records(df: pd.DataFrame, cols: list[str], n: int | None = None) -> list[dict[str, Any]]:
    df = df[cols].head(n) if n else df[cols]
    return json.loads(df.to_json(orient="records"))


def build_snapshot(repo: Repository) -> dict[str, Any]:
    today = today_ist().isoformat()
    snap: dict[str, Any] = {"taken_at": now_iso(), "session_date": today, "observations": []}
    obs: list[str] = snap["observations"]

    # --- Indices: intraday (today) if available, else latest EOD
    intra = _df(repo, "SELECT * FROM intraday_index WHERE session_date = ?", (today,))
    if not intra.empty:
        idx = intra.rename(columns={"last": "level"})
        snap["index_source"] = f"Intraday, last closed 5-min bar ({intra['source'].iloc[0]})"
    else:
        idx = _df(repo, """SELECT index_name, close AS level, change_pct FROM index_levels
                           WHERE trade_date = (SELECT MAX(trade_date) FROM index_levels)""")
        snap["index_source"] = "NSE end-of-day close (previous session)"
    idx = idx[idx["index_name"].isin(KEY_INDICES)]
    snap["indices"] = _records(idx, ["index_name", "level", "change_pct"])
    for r in snap["indices"]:
        if r["index_name"] == "Nifty 50" and r["change_pct"] is not None:
            obs.append(f"Nifty 50 is {'up' if r['change_pct'] >= 0 else 'down'} {abs(r['change_pct']):.2f}% at {r['level']:,.1f}.")
        if r["index_name"] == "India VIX" and r["change_pct"] is not None:
            obs.append(f"India VIX {'rose' if r['change_pct'] >= 0 else 'fell'} {abs(r['change_pct']):.1f}% to {r['level']:.2f}"
                       f" ({'higher' if r['change_pct'] >= 0 else 'lower'} expected volatility).")

    # --- Breadth & movers among F&O stocks
    moves = _df(repo, """SELECT s.symbol, s.name, s.sector, i.change_pct, i.last, i.vwap, i.orb_status, i.relative_volume
                         FROM intraday_snapshot i JOIN stocks s ON s.id = i.stock_id
                         WHERE i.session_date = ? AND s.is_fo_active = 1""", (today,))
    snap["breadth_source"] = "intraday"
    if moves.empty:
        moves = _df(repo, """SELECT s.symbol, s.name, s.sector, (p.close - p.prev_close) / p.prev_close * 100 AS change_pct,
                                    p.close AS last
                             FROM price_history p JOIN stocks s ON s.id = p.stock_id
                             WHERE p.trade_date = (SELECT MAX(trade_date) FROM price_history) AND s.is_fo_active = 1""")
        snap["breadth_source"] = "previous session EOD"
    if not moves.empty:
        adv, dec = int((moves["change_pct"] > 0).sum()), int((moves["change_pct"] < 0).sum())
        snap["breadth"] = {"advances": adv, "declines": dec, "unchanged": int(len(moves) - adv - dec), "total": int(len(moves))}
        obs.append(f"F&O breadth ({snap['breadth_source']}): {adv} advancing vs {dec} declining "
                   f"({'positive' if adv > dec else 'negative' if dec > adv else 'even'}).")
        if "vwap" in moves and moves["vwap"].notna().any():
            above = int((moves["last"] > moves["vwap"]).sum())
            snap["breadth"]["above_vwap"] = above
            obs.append(f"{above} of {len(moves)} F&O stocks trade above their intraday VWAP.")
        if "orb_status" in moves:
            snap["breadth"]["above_orb"] = int((moves["orb_status"] == "ABOVE_ORB").sum())
            snap["breadth"]["below_orb"] = int((moves["orb_status"] == "BELOW_ORB").sum())
        ranked = moves.dropna(subset=["change_pct"]).sort_values("change_pct")
        snap["top_gainers"] = _records(ranked.iloc[::-1], ["symbol", "name", "change_pct"], 5)
        snap["top_losers"] = _records(ranked, ["symbol", "name", "change_pct"], 5)
        sectors = (moves.dropna(subset=["sector", "change_pct"]).groupby("sector")["change_pct"]
                   .agg(["mean", "count"]).query("count >= 3").sort_values("mean", ascending=False).reset_index())
        snap["sectors"] = json.loads(sectors.rename(columns={"mean": "avg_change_pct"}).to_json(orient="records"))
        if len(sectors) >= 2:
            best, worst = sectors.iloc[0], sectors.iloc[-1]
            obs.append(f"Strongest sector: {best['sector']} ({best['mean']:+.2f}% avg); "
                       f"weakest: {worst['sector']} ({worst['mean']:+.2f}% avg).")

    # --- Technical setup counts
    tech = _df(repo, "SELECT timeframe, setup, COUNT(*) AS n FROM technical_signals GROUP BY 1, 2")
    snap["technical"] = {f"{r.timeframe}_{r.setup}": int(r.n) for r in tech.itertuples()}
    b, s = snap["technical"].get("5m_BULLISH", 0), snap["technical"].get("5m_BEARISH", 0)
    if b or s:
        obs.append(f"5-minute technical screen: {b} bullish vs {s} bearish setups.")

    # --- News flow (today, IST) & FII/DII
    news = _df(repo, """SELECT category, COUNT(*) AS n FROM news
                        WHERE sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-1 day') GROUP BY 1 ORDER BY 2 DESC""")
    snap["news_by_category_24h"] = json.loads(news.to_json(orient="records"))
    headlines = _df(repo, """SELECT headline, url, publisher, category, sort_ts FROM news
                             WHERE category IN ('FII/DII', 'General Market', 'Regulatory', 'Sector News')
                             ORDER BY sort_ts DESC LIMIT 8""")
    snap["key_headlines"] = json.loads(headlines.to_json(orient="records"))

    # --- Published research today
    recs = _df(repo, """SELECT normalized_action, COUNT(*) AS n FROM recommendations
                        WHERE published_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-1 day') AND is_flagged = 0
                        GROUP BY 1""")
    snap["published_ratings_24h"] = {r.normalized_action: int(r.n) for r in recs.itertuples()}
    if snap["published_ratings_24h"]:
        parts = ", ".join(f"{k} {v}" for k, v in sorted(snap["published_ratings_24h"].items()))
        obs.append(f"Brokerage ratings published in the last 24h: {parts}.")

    # --- F&O activity (EOD)
    fo = _df(repo, """SELECT s.symbol, f.oi_contracts, f.total_contracts, f.turnover, f.trade_date
                      FROM fo_activity f JOIN stocks s ON s.id = f.stock_id
                      WHERE f.trade_date = (SELECT MAX(trade_date) FROM fo_activity)""")
    if not fo.empty:
        snap["fo_most_active"] = _records(fo.sort_values("turnover", ascending=False), ["symbol", "total_contracts", "turnover"], 5)
        snap["fo_date"] = fo["trade_date"].iloc[0]
        obs.append(f"Most active stock derivative on {snap['fo_date']}: {snap['fo_most_active'][0]['symbol']} "
                   f"(₹{snap['fo_most_active'][0]['turnover'] / 1e7:,.0f} cr notional).")

    # --- Why is the market up / down / flat (live intraday reading)
    try:
        from analysis.observation import build_observation
        snap["explanation"] = build_observation(repo.conn)
    except Exception as exc:  # the snapshot must not fail because of the narrative
        log.warning("market observation failed: %s", exc)
    return snap


def run_market_snapshot(repo: Repository, settings: Settings) -> dict[str, Any]:
    snap = build_snapshot(repo)
    ai_summary = ai_model = None
    if settings.ai_enabled:
        try:
            from processing.ai.assistant import AIAssistant
            assistant = AIAssistant(settings)
            ai_summary = assistant.summarize_market(snap)
            ai_model = settings.ai_model if ai_summary else None
        except Exception as exc:
            log.warning("AI market summary failed: %s", exc)
    snap_id = repo.insert_market_snapshot(snap["taken_at"], json.dumps(snap, default=str), ai_summary, ai_model)
    log.info("market snapshot %s stored with %s observations", snap_id, len(snap["observations"]))
    return {"snapshot_id": snap_id, "observations": len(snap["observations"])}

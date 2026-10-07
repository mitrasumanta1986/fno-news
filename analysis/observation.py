"""Live "Market Observation": why is the market up / down / flat right now?

Rule-based reading of the latest intraday data (5-min bars) and today's headlines. It explains what
is moving the index — sectors, heavyweights, breadth, volatility, intraday range — and lists the news
associated with the biggest moves. Headlines are associations, not confirmed causes. No forecasts.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import pandas as pd

from config.settings import load_yaml

FLAT_PCT = 0.20     # |Nifty change| below this = flat
SHARP_PCT = 1.00    # at or above this = sharp move
SECTOR_MOVE_PCT = 0.50
STOCK_MOVE_PCT = 2.0
SECTOR_INDICES = {"Nifty Auto", "Nifty Bank", "Nifty Consumer Durables", "Nifty Energy", "Nifty FMCG",
                  "Nifty Financial Services", "Nifty Healthcare Index", "Nifty IT", "Nifty Media", "Nifty Metal",
                  "Nifty Oil & Gas", "Nifty PSU Bank", "Nifty Pharma", "Nifty Private Bank", "Nifty Realty"}
SECTORS_SHOWN = 3   # per side
NEWS_HOURS = 18

MACRO_BUCKETS = [
    ("🌍 Global markets", ("global market", "wall street", "dow ", "nasdaq", "s&p 500", "asian market", "kospi",
                          "nikkei", "hang seng", "us market", "us stocks")),
    ("🏦 FII / DII flows", ("fii", "dii", "foreign investor", "foreign portfolio", "fpi")),
    ("🛢️ Crude oil", ("crude", "oil price", "brent")),
    ("💱 Rupee / dollar", ("rupee", "dollar index", "usd/inr")),
    ("📈 Rates / bonds / inflation", ("yield", "rate hike", "rate cut", "repo", "rbi", "fed ", "inflation", "cpi")),
    ("⚠️ Geopolitics / policy", ("war", "middle east", "tariff", "sanction", "geopolit", "iran", "israel", "china")),
]


def nifty_weights() -> dict[str, float]:
    try:
        raw = load_yaml("nifty_weights.yaml")
    except FileNotFoundError:
        return {}
    return {str(k): float(v) for k, v in raw.items()}


def load_inputs(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """Latest intraday session for indices + F&O stocks, and the last NEWS_HOURS of headlines."""
    q = lambda sql, p=(): pd.read_sql_query(sql, conn, params=p)  # noqa: E731
    since = f"-{NEWS_HOURS} hours"
    return {
        "indices": q("SELECT * FROM intraday_index WHERE session_date = (SELECT MAX(session_date) FROM intraday_index)"),
        "moves": q("""SELECT s.symbol, s.name, s.sector, i.change_pct, i.last, i.vwap, i.relative_volume, i.session_date
                      FROM intraday_snapshot i JOIN stocks s ON s.id = i.stock_id
                      WHERE s.is_fo_active = 1 AND i.session_date = (SELECT MAX(session_date) FROM intraday_snapshot)"""),
        "news": q("""SELECT headline, url, publisher, category, sort_ts FROM news
                     WHERE sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now', ?) ORDER BY sort_ts DESC""", (since,)),
        "stock_news": q("""SELECT s.symbol, n.headline, n.url, n.publisher, n.sort_ts
                           FROM news_stocks ns JOIN news n ON n.id = ns.news_id JOIN stocks s ON s.id = ns.stock_id
                           WHERE n.sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now', ?)
                           ORDER BY n.sort_ts DESC""", (since,)),
    }


def _pct(v: float) -> str:
    return f"{v:+.2f}%"


def _ev(rows: pd.DataFrame, n: int = 2) -> list[dict[str, Any]]:
    if rows is None or rows.empty:
        return []
    rows = rows.drop_duplicates("headline").head(n)
    return json.loads(rows[["headline", "url", "publisher"]].to_json(orient="records"))


def _strip(name: str) -> str:
    return name.replace("Nifty ", "")


def explain_market(indices: pd.DataFrame, moves: pd.DataFrame, news: pd.DataFrame | None = None,
                   stock_news: pd.DataFrame | None = None, weights: dict[str, float] | None = None) -> dict[str, Any] | None:
    news = news if news is not None else pd.DataFrame()
    stock_news = stock_news if stock_news is not None else pd.DataFrame()
    weights = nifty_weights() if weights is None else weights
    if indices is None or indices.empty:
        return None
    by_name = {r["index_name"]: r for r in indices.to_dict("records")}
    nifty = by_name.get("Nifty 50")
    if not nifty or nifty.get("change_pct") is None or pd.isna(nifty.get("change_pct")):
        return None

    chg, last = float(nifty["change_pct"]), float(nifty["last"])
    prev = float(nifty["prev_close"]) if nifty.get("prev_close") else last / (1 + chg / 100)
    pts = last - prev
    trend = "FLAT" if abs(chg) < FLAT_PCT else "UP" if chg > 0 else "DOWN"
    sign = 1 if chg > 0 else -1
    size = "sharply " if abs(chg) >= SHARP_PCT else "" if abs(chg) >= 0.5 else "slightly "
    title = (f"Market is FLAT — Nifty 50 {_pct(chg)} ({pts:+,.0f} pts) at {last:,.1f}" if trend == "FLAT" else
             f"Market is {size}{trend} — Nifty 50 {_pct(chg)} ({pts:+,.0f} pts) at {last:,.1f}")
    drivers: list[dict[str, Any]] = []
    summary: list[str] = []

    moves = moves if moves is not None else pd.DataFrame()
    moves = moves.dropna(subset=["change_pct"]) if not moves.empty else moves

    def news_for(symbols: list[str]) -> pd.DataFrame:
        if stock_news.empty:
            return stock_news
        return stock_news[stock_news["symbol"].isin(symbols)]

    # 1. Sectoral indices: who is dragging, who is supporting
    sect = sorted(((n, float(r["change_pct"])) for n, r in by_name.items()
                   if n in SECTOR_INDICES and r.get("change_pct") is not None and not pd.isna(r["change_pct"])),
                  key=lambda x: x[1])
    down = [(n, c) for n, c in sect if c <= -SECTOR_MOVE_PCT][:SECTORS_SHOWN]
    up = [(n, c) for n, c in reversed(sect) if c >= SECTOR_MOVE_PCT][:SECTORS_SHOWN]
    if down:
        drivers.append({"tone": -1, "text": "Sector drag: " + ", ".join(f"{_strip(n)} {_pct(c)}" for n, c in down)})
    if up:
        drivers.append({"tone": 1, "text": "Sector support: " + ", ".join(f"{_strip(n)} {_pct(c)}" for n, c in up)})
    lead, offset = (down, up) if trend == "DOWN" else (up, down)
    if trend != "FLAT" and lead:
        s = f"{'Weakness' if trend == 'DOWN' else 'Gains'} led by " + " and ".join(f"{_strip(n)} ({_pct(c)})" for n, c in lead[:2])
        if offset:
            s += ", partly offset by " + " and ".join(f"{_strip(n)} ({_pct(c)})" for n, c in offset[:2])
        summary.append(s + ".")
    elif trend == "FLAT" and up and down:
        summary.append(f"Sectors are pulling in opposite directions — {_strip(up[0][0])} {_pct(up[0][1])} vs "
                       f"{_strip(down[0][0])} {_pct(down[0][1])} — cancelling out at the index level.")
    elif trend == "FLAT":
        summary.append("No sector or heavyweight is moving enough to push the index either way.")

    # 2. Heavyweights: approximate contribution to Nifty points
    if not moves.empty and weights:
        hw = moves[moves["symbol"].isin(weights)].copy()
        if not hw.empty:
            total_w = sum(weights.values())
            hw["pts"] = hw["symbol"].map(weights) / total_w * hw["change_pct"] / 100 * prev
            hw = hw.sort_values("pts")
            neg, pos = hw[hw["pts"] < -0.5].head(3), hw[hw["pts"] > 0.5].iloc[::-1].head(3)
            fmt_hw = lambda d: ", ".join(f"{r.symbol} {_pct(r.change_pct)} (~{r.pts:+.0f} pts)" for r in d.itertuples())  # noqa: E731
            if not neg.empty:
                drivers.append({"tone": -1, "text": "Heavyweights dragging Nifty: " + fmt_hw(neg),
                                "evidence": _ev(news_for(neg["symbol"].tolist()))})
            if not pos.empty:
                drivers.append({"tone": 1, "text": "Heavyweights supporting Nifty: " + fmt_hw(pos),
                                "evidence": _ev(news_for(pos["symbol"].tolist()))})

    # 3. Breadth (F&O universe) and whether it agrees with the index
    if not moves.empty:
        adv, dec = int((moves["change_pct"] > 0).sum()), int((moves["change_pct"] < 0).sum())
        total = len(moves)
        tone = 1 if adv > dec else -1 if dec > adv else 0
        text = f"Breadth: {adv} F&O stocks up vs {dec} down (of {total})"
        if trend == "UP" and dec > adv:
            text += " — narrow rally: index lifted by a few heavyweights while most stocks fall"
        elif trend == "DOWN" and adv > dec:
            text += " — index fall is concentrated in heavyweights; the broader market is holding up"
        elif trend != "FLAT" and tone == sign:
            text += f" — broad-based {'buying' if trend == 'UP' else 'selling'}"
        elif trend == "FLAT":
            text += " — mixed market, no clear direction" if abs(adv - dec) < total * 0.2 else \
                f" — stocks lean {'positive' if adv > dec else 'negative'} even though the index is flat"
        drivers.append({"tone": tone, "text": text + "."})
        summary.append(f"Breadth is {'positive' if tone > 0 else 'negative' if tone < 0 else 'even'} ({adv} up / {dec} down).")
        if moves["vwap"].notna().any():
            above = int((moves["last"] > moves["vwap"]).sum())
            share = above / total
            drivers.append({"tone": 1 if share > 0.6 else -1 if share < 0.4 else 0,
                            "text": f"{above} of {total} F&O stocks trade above intraday VWAP — "
                                    + ("buyers in control intraday." if share > 0.6 else
                                       "sellers in control intraday." if share < 0.4 else "no clear intraday control.")})

    # 4. Volatility
    vix = by_name.get("India VIX")
    if vix and vix.get("change_pct") is not None and not pd.isna(vix["change_pct"]):
        vchg, vlvl = float(vix["change_pct"]), float(vix["last"])
        mood = ("rising fear / hedging demand" if vchg >= 3 else "slightly more caution" if vchg > 0
                else "fear easing, calmer sentiment" if vchg <= -3 else "steady sentiment")
        lvl = " (elevated — expect bigger swings)" if vlvl >= 20 else " (low — calm market)" if vlvl < 12 else ""
        drivers.append({"tone": -1 if vchg > 0 else 1, "text": f"India VIX {_pct(vchg)} at {vlvl:.2f}{lvl}: {mood}."})
        summary.append(f"India VIX is {'up' if vchg >= 0 else 'down'} {abs(vchg):.1f}%.")

    # 5. Intraday path: where the index sits in today's range
    hi, lo = nifty.get("day_high"), nifty.get("day_low")
    if hi and lo and hi > lo:
        pos = (last - lo) / (hi - lo)
        rng = (hi - lo) / prev * 100
        where = ("near the day's high — buying into the session" if pos >= 0.8 else
                 "near the day's low — selling pressure persists" if pos <= 0.2 else "in the middle of the day's range")
        text = f"Nifty range today {lo:,.0f}–{hi:,.0f} ({rng:.2f}% wide); trading {where}"
        if last < prev < hi:
            text += f". It traded above yesterday's close ({prev:,.0f}) earlier but slipped into the red"
        elif last > prev > lo:
            text += f". It dipped below yesterday's close ({prev:,.0f}) earlier but recovered into the green"
        if rng < 0.5:
            text += ". Very narrow range — an indecisive, low-conviction session"
        drivers.append({"tone": 1 if pos >= 0.6 else -1 if pos <= 0.4 else 0, "text": text + "."})

    # 6. Biggest stock moves and the news linked to them
    if not moves.empty:
        big = moves[moves["change_pct"].abs() >= STOCK_MOVE_PCT]
        for frame, tone in ((big.sort_values("change_pct").head(3), -1), (big.sort_values("change_pct").iloc[::-1].head(3), 1)):
            frame = frame[(frame["change_pct"] < 0) if tone < 0 else (frame["change_pct"] > 0)]
            for r in frame.itertuples():
                drivers.append({"tone": tone, "kind": "stock", "text": f"{r.symbol} {_pct(r.change_pct)}"
                                + (f" · {r.sector}" if isinstance(r.sector, str) else ""),
                                "evidence": _ev(news_for([r.symbol]), 1)})

    # 7. Macro / global backdrop from today's headlines
    backdrop = []
    if not news.empty:
        low = news["headline"].str.lower()
        for label, words in MACRO_BUCKETS:
            pattern = r"\b(?:" + "|".join(re.escape(w.strip()) for w in words) + r")\b"
            hit = news[low.str.contains(pattern, regex=True, na=False)]
            if label.startswith("🏦"):
                hit = pd.concat([news[news["category"] == "FII/DII"], hit])
            ev = _ev(hit, 2)
            if ev:
                backdrop.append({"label": label, "evidence": ev})

    return {
        "trend": trend, "change_pct": chg, "points": pts, "level": last, "title": title,
        "summary": " ".join(summary), "drivers": drivers, "backdrop": backdrop,
        "as_of": nifty.get("bar_time"), "session_date": nifty.get("session_date"), "source": nifty.get("source"),
    }


def build_observation(conn: sqlite3.Connection) -> dict[str, Any] | None:
    d = load_inputs(conn)
    return explain_market(d["indices"], d["moves"], d["news"], d["stock_news"])

import json

import numpy as np
import pandas as pd

from analysis.market import build_snapshot
from analysis.scorecard import build_scorecard, fundamental_reading, movement_metrics, movement_reading, technical_reading
from technical.intraday import stock_snapshot


def _two_sessions():
    prev = pd.date_range("2026-09-25 09:15", periods=75, freq="5min", tz="Asia/Kolkata")
    today = pd.date_range("2026-09-28 09:15", periods=24, freq="5min", tz="Asia/Kolkata")
    idx = prev.append(today)
    close = np.r_[np.full(75, 100.0), np.linspace(101, 106, 24)]
    df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000.0}, index=idx)
    return df


def test_intraday_snapshot_orb_vwap_relative_volume():
    snap = stock_snapshot(_two_sessions(), avg_volume_20d=75_000)
    assert snap["prev_close"] == 100.0 and snap["last"] == 106.0
    assert round(snap["change_pct"], 2) == 6.0
    assert snap["orb_high"] == round(float(np.linspace(101, 106, 24)[2]) + 0.5, 4)
    assert snap["orb_status"] == "ABOVE_ORB"
    # 24 bars * 1000 = 24,000 traded in 120 of 375 minutes vs 75,000/day average -> 1.0x
    assert round(snap["relative_volume"], 2) == 1.0
    assert snap["vwap"] < snap["last"]


def test_readings_are_descriptive():
    assert technical_reading("BULLISH", "NONE") == "Bullish (5m)"
    assert technical_reading("NONE", None) == "No setup"
    assert movement_reading(4, 8) == "Strong up-move" and movement_reading(-4, -8) == "Strong down-move"
    assert "High ROE" in fundamental_reading(20, 0.22, 0.2)
    assert fundamental_reading(None, None, None) == "N/A"


def test_scorecard_builds_all_factors():
    stocks = pd.DataFrame({"id": [1, 2, 3], "symbol": ["A", "B", "C"], "name": ["a", "b", "c"], "sector": ["X", "X", "Y"]})
    rows = []
    for sid, drift in ((1, 1.0), (2, -1.0), (3, 0.0)):
        for i in range(30):
            c = 100 + drift * i
            rows.append({"stock_id": sid, "trade_date": f"2026-08-{i + 1:02d}", "high": c + 1, "low": c - 1, "close": c, "volume": 1000 * sid})
    move = movement_metrics(pd.DataFrame(rows))
    fo = pd.DataFrame({"stock_id": [1, 2, 3], "turnover": [3e9, 2e9, 1e9], "total_contracts": [3, 2, 1], "oi_contracts": [1, 1, 1]})
    card = build_scorecard(stocks, move, pd.DataFrame(), fo, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert set(card["Movement"]) == {"Strong up-move", "Strong down-move", "Mild down-trend"}
    assert set(card["Liquidity"]) <= {"High", "Medium", "Low"}
    assert not {"BUY", "SELL"} & set(card.columns)


def _obs_inputs(nifty_chg):
    indices = pd.DataFrame([
        {"index_name": "Nifty 50", "last": 100 + nifty_chg, "prev_close": 100.0, "change_pct": nifty_chg,
         "day_high": 101.5, "day_low": 98.5, "bar_time": "t", "session_date": "d", "source": "s"},
        {"index_name": "Nifty Auto", "last": 97.0, "prev_close": 100.0, "change_pct": -3.0},
        {"index_name": "Nifty IT", "last": 102.0, "prev_close": 100.0, "change_pct": 2.0},
        {"index_name": "India VIX", "last": 14.0, "prev_close": 13.0, "change_pct": 7.7},
    ])
    moves = pd.DataFrame({"symbol": ["BAJAJ-AUTO", "INFY", "X"], "name": ["b", "i", "x"], "sector": ["Auto", "IT", "Y"],
                          "change_pct": [-7.0, 2.5, -0.1], "last": [1, 1, 1], "vwap": [2, 0.5, 2]})
    news = pd.DataFrame({"headline": ["Rupee slips against dollar", "Hexaware results"], "url": ["https://a", "https://b"],
                         "publisher": ["p", "p"], "category": ["General Market", "Results"], "sort_ts": ["t", "t"]})
    stock_news = pd.DataFrame({"symbol": ["BAJAJ-AUTO"], "headline": ["Bajaj Auto falls after weak sales"],
                               "url": ["https://c"], "publisher": ["p"], "sort_ts": ["t"]})
    return indices, moves, news, stock_news


def test_market_observation_explains_direction():
    from analysis.observation import explain_market

    weights = {"BAJAJ-AUTO": 1.0, "INFY": 5.0}
    down = explain_market(*_obs_inputs(-0.8), weights=weights)
    assert down["trend"] == "DOWN" and "Auto" in down["summary"].split("offset")[0]
    texts = " | ".join(d["text"] for d in down["drivers"])
    assert "Sector drag: Auto" in texts and "India VIX" in texts and "BAJAJ-AUTO -7.00%" in texts
    stock = next(d for d in down["drivers"] if d.get("kind") == "stock" and "BAJAJ" in d["text"])
    assert stock["evidence"][0]["headline"].startswith("Bajaj Auto falls")
    labels = [b["label"] for b in down["backdrop"]]
    assert any("Rupee" in label for label in labels) and not any("Geopolitics" in label for label in labels)
    json.dumps(down)

    assert explain_market(*_obs_inputs(0.9), weights=weights)["trend"] == "UP"
    flat = explain_market(*_obs_inputs(0.05), weights=weights)
    assert flat["trend"] == "FLAT" and "cancelling out" in flat["summary"]
    assert explain_market(pd.DataFrame(), pd.DataFrame()) is None


def test_market_snapshot_on_seeded_db(temp_db):
    temp_db.upsert_index_levels([{"index_name": "Nifty 50", "trade_date": "2026-09-25", "close": 23000.0, "change": -100.0,
                                  "change_pct": -0.43, "source": "t"}])
    temp_db.upsert_prices([{"stock_id": sid, "trade_date": "2026-09-25", "open": 1, "high": 1, "low": 1, "close": c,
                            "prev_close": 100.0, "volume": 1, "source": "t"} for sid, c in ((1, 101.0), (2, 99.0), (3, 98.0))])
    snap = build_snapshot(temp_db)
    json.dumps(snap)  # must be serialisable
    assert snap["breadth"]["advances"] == 1 and snap["breadth"]["declines"] == 2
    assert any("Nifty 50 is down 0.43%" in o for o in snap["observations"])
    assert all("buy" not in o.lower().split() for o in snap["observations"])

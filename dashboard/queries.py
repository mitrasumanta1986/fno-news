"""Read-only queries for the dashboard, cached with short TTLs."""
from __future__ import annotations

from contextlib import closing
from typing import Any

import pandas as pd
import streamlit as st

from database.connection import connect

NEWS_TTL = 60
LIVE_TTL = 30
STATIC_TTL = 600


def _df(sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    with closing(connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def _scalar(sql: str, params: tuple = ()) -> Any:
    with closing(connect()) as conn:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None


def clear_caches() -> None:
    st.cache_data.clear()


_LATEST_PRICE = """
    SELECT stock_id, close, prev_close, trade_date FROM (
      SELECT ph.*, ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY trade_date DESC) rn FROM price_history ph
    ) WHERE rn = 1"""

_REC_SELECT = """
    SELECT r.id, r.stock_id, s.name AS stock, r.symbol, r.original_action, r.normalized_action, r.rating_change,
           b.canonical_name AS brokerage, a.name AS analyst, r.target_price, r.target_text, r.stop_loss,
           r.price_at_reco, r.time_horizon_original, r.time_horizon, r.published_at, r.source_name, r.source_url,
           r.article_url, r.retrieved_at, r.extraction_method, r.evidence_text, r.confidence, r.review_note,
           r.is_flagged, lp.close AS last_close, lp.trade_date AS close_date,
           (SELECT COUNT(*) FROM recommendation_mentions m WHERE m.recommendation_id = r.id) AS mentions
    FROM recommendations r
    JOIN stocks s ON s.id = r.stock_id
    LEFT JOIN brokerages b ON b.id = r.brokerage_id
    LEFT JOIN analysts a ON a.id = r.analyst_id
    LEFT JOIN ({latest}) lp ON lp.stock_id = r.stock_id
""".replace("{latest}", _LATEST_PRICE)


@st.cache_data(ttl=NEWS_TTL)
def app_state() -> dict[str, str]:
    df = _df("SELECT key, value FROM app_state")
    return dict(zip(df["key"], df["value"]))


@st.cache_data(ttl=STATIC_TTL)
def stock_list() -> pd.DataFrame:
    return _df("SELECT id, symbol, name, sector FROM stocks WHERE is_fo_active = 1 ORDER BY symbol")


@st.cache_data(ttl=NEWS_TTL)
def index_levels(names: tuple[str, ...]) -> pd.DataFrame:
    marks = ",".join("?" * len(names))
    return _df(f"""SELECT index_name, trade_date, close, change, change_pct FROM (
                     SELECT il.*, ROW_NUMBER() OVER (PARTITION BY index_name ORDER BY trade_date DESC) rn
                     FROM index_levels il WHERE index_name IN ({marks})) WHERE rn = 1""", names)


@st.cache_data(ttl=LIVE_TTL)
def live_index_levels(names: tuple[str, ...]) -> pd.DataFrame:
    """Latest 5-min intraday level per index, falling back to NSE EOD where intraday is missing or older."""
    marks = ",".join("?" * len(names))
    intra = _df(f"""SELECT index_name, session_date AS as_of, last AS close, prev_close, change_pct, day_high, day_low,
                           bar_time, source, 'live' AS kind
                    FROM intraday_index WHERE index_name IN ({marks})""", names)
    eod = _df(f"""SELECT index_name, trade_date AS as_of, close, close - change AS prev_close, change_pct,
                         NULL AS day_high, NULL AS day_low, NULL AS bar_time, source, 'eod' AS kind FROM (
                    SELECT il.*, ROW_NUMBER() OVER (PARTITION BY index_name ORDER BY trade_date DESC) rn
                    FROM index_levels il WHERE index_name IN ({marks})) WHERE rn = 1""", names)
    both = pd.concat([intra, eod], ignore_index=True)
    if both.empty:
        return both
    # newest date wins; on a tie the NSE close beats Yahoo's delayed last bar (keep the bar's high/low)
    both["_eod"] = (both["kind"] == "eod").astype(int)
    best = both.sort_values(["as_of", "_eod"], ascending=False).drop_duplicates("index_name")
    live = intra.set_index(["index_name", "as_of"])[["day_high", "day_low"]]
    for i, r in best[best["kind"] == "eod"].iterrows():
        if (r["index_name"], r["as_of"]) in live.index:
            best.loc[i, ["day_high", "day_low"]] = live.loc[(r["index_name"], r["as_of"])].values
    return best.drop(columns="_eod").reset_index(drop=True)


@st.cache_data(ttl=LIVE_TTL)
def market_observation() -> dict[str, Any] | None:
    from analysis.observation import build_observation

    with closing(connect()) as conn:
        return build_observation(conn)


@st.cache_data(ttl=NEWS_TTL)
def counts() -> dict[str, Any]:
    with closing(connect()) as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "recs_24h": q("SELECT COUNT(*) FROM recommendations WHERE retrieved_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-1 day') AND is_flagged = 0"),
            "recs_7d": q("SELECT COUNT(*) FROM recommendations WHERE published_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-7 day') AND is_flagged = 0"),
            "news_24h": q("SELECT COUNT(*) FROM news WHERE sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-1 day')"),
            "stocks": q("SELECT COUNT(*) FROM stocks WHERE is_fo_active = 1"),
            "sources_active": q("SELECT COUNT(*) FROM sources WHERE status = 'ACTIVE'"),
            "sources_enabled": q("SELECT COUNT(*) FROM sources WHERE enabled = 1 AND kind NOT IN ('SYSTEM')"),
        }


@st.cache_data(ttl=NEWS_TTL)
def fo_stocks_table() -> pd.DataFrame:
    return _df(f"""
        WITH lp AS ({_LATEST_PRICE}),
        ln AS (SELECT ns.stock_id, n.headline, n.url, n.sort_ts,
                      ROW_NUMBER() OVER (PARTITION BY ns.stock_id ORDER BY n.sort_ts DESC) rn
               FROM news_stocks ns JOIN news n ON n.id = ns.news_id),
        lr AS (SELECT r.stock_id, r.original_action, r.normalized_action, b.canonical_name AS brokerage,
                      a.name AS analyst, r.target_price, r.stop_loss, r.time_horizon_original, r.published_at,
                      r.source_name, r.article_url,
                      ROW_NUMBER() OVER (PARTITION BY r.stock_id ORDER BY r.published_at DESC) rn
               FROM recommendations r LEFT JOIN brokerages b ON b.id = r.brokerage_id
               LEFT JOIN analysts a ON a.id = r.analyst_id WHERE r.is_flagged = 0)
        SELECT s.name, s.symbol, s.sector, lp.close, lp.prev_close, lp.trade_date AS price_date,
               s.is_fo_active, s.fo_lot_size, ln.headline AS latest_news, ln.url AS latest_news_url,
               ln.sort_ts AS latest_news_at, lr.original_action, lr.normalized_action, lr.brokerage, lr.analyst,
               lr.target_price, lr.stop_loss, lr.time_horizon_original, lr.published_at AS rec_date,
               lr.source_name, lr.article_url
        FROM stocks s
        LEFT JOIN lp ON lp.stock_id = s.id
        LEFT JOIN ln ON ln.stock_id = s.id AND ln.rn = 1
        LEFT JOIN lr ON lr.stock_id = s.id AND lr.rn = 1
        WHERE s.is_fo_active = 1 ORDER BY s.symbol""")


@st.cache_data(ttl=NEWS_TTL)
def news(days: int = 7, categories: tuple[str, ...] = (), symbol: str | None = None, limit: int = 500,
         keyword: str | None = None) -> pd.DataFrame:
    where, params = ["n.sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now', ?)"], [f"-{int(days)} day"]
    if categories:
        where.append(f"n.category IN ({','.join('?' * len(categories))})")
        params += list(categories)
    if symbol:
        where.append("EXISTS (SELECT 1 FROM news_stocks x JOIN stocks xs ON xs.id = x.stock_id WHERE x.news_id = n.id AND xs.symbol = ?)")
        params.append(symbol)
    if keyword:
        where.append("(n.headline LIKE ? OR n.snippet LIKE ?)")
        params += [f"%{keyword}%", f"%{keyword}%"]
    params.append(limit)
    return _df(f"""
        SELECT n.id, n.headline, n.snippet, n.url, n.publisher, n.category, n.sort_ts, n.published_at,
               n.story_cluster_id, n.ai_summary,
               (SELECT GROUP_CONCAT(s.symbol, ', ') FROM news_stocks ns JOIN stocks s ON s.id = ns.stock_id
                 WHERE ns.news_id = n.id) AS symbols,
               (SELECT COUNT(*) FROM news c WHERE c.story_cluster_id = n.story_cluster_id) AS cluster_size
        FROM news n WHERE {' AND '.join(where)}
        ORDER BY n.sort_ts DESC LIMIT ?""", tuple(params))


@st.cache_data(ttl=NEWS_TTL)
def recommendations(days: int = 30, symbol: str | None = None, include_flagged: bool = False) -> pd.DataFrame:
    where, params = ["r.published_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now', ?)"], [f"-{int(days)} day"]
    if symbol:
        where.append("r.symbol = ?")
        params.append(symbol)
    if not include_flagged:
        where.append("r.is_flagged = 0")
    return _df(f"{_REC_SELECT} WHERE {' AND '.join(where)} ORDER BY r.published_at DESC", tuple(params))


@st.cache_data(ttl=NEWS_TTL)
def recommendation_mentions(rec_ids: tuple[int, ...]) -> pd.DataFrame:
    if not rec_ids:
        return pd.DataFrame()
    marks = ",".join("?" * len(rec_ids))
    return _df(f"""SELECT m.recommendation_id, m.is_original_source, n.publisher, n.headline, n.url, n.sort_ts
                   FROM recommendation_mentions m JOIN news n ON n.id = m.news_id
                   WHERE m.recommendation_id IN ({marks}) ORDER BY n.sort_ts""", rec_ids)


@st.cache_data(ttl=NEWS_TTL)
def stock_detail(symbol: str) -> dict[str, Any]:
    info = _df("SELECT * FROM stocks WHERE symbol = ?", (symbol,))
    prices = _df("""SELECT ph.trade_date, ph.open, ph.high, ph.low, ph.close, ph.prev_close, ph.volume
                    FROM price_history ph JOIN stocks s ON s.id = ph.stock_id WHERE s.symbol = ?
                    ORDER BY ph.trade_date""", (symbol,))
    fo = _df("""SELECT f.* FROM fo_activity f JOIN stocks s ON s.id = f.stock_id WHERE s.symbol = ?
                ORDER BY f.trade_date DESC LIMIT 1""", (symbol,))
    tech = _df("""SELECT t.* FROM technical_signals t JOIN stocks s ON s.id = t.stock_id WHERE s.symbol = ?""", (symbol,))
    return {"info": info, "prices": prices, "fo": fo, "tech": tech}


@st.cache_data(ttl=NEWS_TTL)
def fo_activity_latest() -> pd.DataFrame:
    return _df("""
        SELECT s.symbol, s.name, s.sector, f.* FROM fo_activity f JOIN stocks s ON s.id = f.stock_id
        WHERE f.trade_date = (SELECT MAX(trade_date) FROM fo_activity) AND s.is_fo_active = 1""")


@st.cache_data(ttl=NEWS_TTL)
def technical_signals(timeframe: str) -> pd.DataFrame:
    return _df("""SELECT s.symbol, s.name, s.sector, t.* FROM technical_signals t JOIN stocks s ON s.id = t.stock_id
                  WHERE t.timeframe = ? AND s.is_fo_active = 1""", (timeframe,))


@st.cache_data(ttl=NEWS_TTL)
def intraday_snapshot() -> pd.DataFrame:
    return _df("""SELECT s.symbol, s.name, s.sector, i.* FROM intraday_snapshot i JOIN stocks s ON s.id = i.stock_id
                  WHERE s.is_fo_active = 1 AND i.session_date = (SELECT MAX(session_date) FROM intraday_snapshot)""")


@st.cache_data(ttl=NEWS_TTL)
def intraday_index() -> pd.DataFrame:
    return _df("SELECT * FROM intraday_index WHERE session_date = (SELECT MAX(session_date) FROM intraday_index)")


@st.cache_data(ttl=NEWS_TTL)
def market_snapshots(limit: int = 60) -> pd.DataFrame:
    return _df("SELECT id, taken_at, payload, ai_summary, ai_model FROM market_snapshots ORDER BY taken_at DESC LIMIT ?", (limit,))


@st.cache_data(ttl=300)
def scorecard_frame() -> pd.DataFrame:
    from analysis.scorecard import build_scorecard, movement_metrics

    stocks = _df("SELECT id, symbol, name, sector FROM stocks WHERE is_fo_active = 1")
    prices = _df("SELECT stock_id, trade_date, high, low, close, volume FROM price_history")
    fundamentals = _df("SELECT stock_id, pe, pb, roe, debt_to_equity, market_cap, earnings_growth, revenue_growth, "
                       "profit_margin, dividend_yield, high_52w, low_52w, updated_at AS fundamentals_at FROM fundamentals")
    fo = _df("""SELECT stock_id, total_contracts, turnover, oi_contracts, oi_change FROM fo_activity
                WHERE trade_date = (SELECT MAX(trade_date) FROM fo_activity)""")
    tech = _df("""SELECT stock_id,
                    MAX(CASE WHEN timeframe='5m' THEN setup END) AS setup_5m,
                    MAX(CASE WHEN timeframe='1d' THEN setup END) AS setup_1d,
                    MAX(CASE WHEN timeframe='1d' THEN rsi END) AS rsi_1d,
                    MAX(CASE WHEN timeframe='1d' THEN adx END) AS adx_1d,
                    MAX(CASE WHEN timeframe='5m' THEN rsi END) AS rsi_5m
                  FROM technical_signals GROUP BY stock_id""")
    news_counts = _df("""SELECT ns.stock_id, COUNT(*) AS news_7d FROM news_stocks ns JOIN news n ON n.id = ns.news_id
                         WHERE n.sort_ts >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-7 day') GROUP BY ns.stock_id""")
    rec_counts = _df("""SELECT stock_id,
                          SUM(normalized_action IN ('BUY','ACCUMULATE')) AS pos_recs,
                          SUM(normalized_action IN ('SELL','REDUCE')) AS neg_recs,
                          SUM(normalized_action IN ('HOLD','NEUTRAL')) AS neutral_recs
                        FROM recommendations WHERE is_flagged = 0
                          AND published_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-30 day') GROUP BY stock_id""")
    movement = movement_metrics(prices) if not prices.empty else pd.DataFrame()
    return build_scorecard(stocks, movement, fundamentals, fo, tech, news_counts, rec_counts)


@st.cache_data(ttl=NEWS_TTL)
def sources() -> pd.DataFrame:
    return _df("""SELECT s.*, (SELECT COUNT(*) FROM news n WHERE n.source_id = s.id
                              AND n.retrieved_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00','now','-1 day')) AS items_24h
                  FROM sources s ORDER BY s.enabled DESC, s.name""")


@st.cache_data(ttl=NEWS_TTL)
def fetch_logs(limit: int = 200) -> pd.DataFrame:
    return _df("""SELECT l.started_at, COALESCE(s.name, l.job) AS source, l.job, l.status, l.items_fetched, l.items_new,
                         l.items_duplicate, l.items_irrelevant, l.recs_extracted, l.duration_ms, l.error
                  FROM fetch_logs l LEFT JOIN sources s ON s.id = l.source_id
                  ORDER BY l.started_at DESC LIMIT ?""", (limit,))


@st.cache_data(ttl=NEWS_TTL)
def watchlist() -> pd.DataFrame:
    return _df(f"""
        SELECT s.id AS stock_id, s.symbol, s.name, s.sector, w.added_at, w.last_viewed_at, lp.close, lp.prev_close,
               lp.trade_date,
               (SELECT COUNT(*) FROM news_stocks ns JOIN news n ON n.id = ns.news_id
                 WHERE ns.stock_id = s.id AND n.retrieved_at > w.last_viewed_at) AS new_news,
               (SELECT COUNT(*) FROM recommendations r WHERE r.stock_id = s.id AND r.retrieved_at > w.last_viewed_at
                 AND r.is_flagged = 0) AS new_recs
        FROM watchlist w JOIN stocks s ON s.id = w.stock_id
        LEFT JOIN ({_LATEST_PRICE}) lp ON lp.stock_id = s.id ORDER BY s.symbol""")


@st.cache_data(ttl=NEWS_TTL)
def search_all(term: str) -> dict[str, pd.DataFrame]:
    like = f"%{term}%"
    stocks = _df("""SELECT symbol, name, sector FROM stocks WHERE is_fo_active = 1 AND
                    (symbol LIKE ? OR name LIKE ? OR sector LIKE ?) ORDER BY symbol LIMIT 100""", (like, like, like))
    recs = _df(f"""{_REC_SELECT} WHERE r.is_flagged = 0 AND (b.canonical_name LIKE ? OR a.name LIKE ? OR r.symbol LIKE ?
                   OR s.name LIKE ? OR s.sector LIKE ?) ORDER BY r.published_at DESC LIMIT 200""",
               (like, like, like, like, like))
    news_df = _df("""SELECT n.headline, n.url, n.publisher, n.category, n.sort_ts,
                       (SELECT GROUP_CONCAT(s.symbol, ', ') FROM news_stocks ns JOIN stocks s ON s.id = ns.stock_id
                         WHERE ns.news_id = n.id) AS symbols
                     FROM news n WHERE n.headline LIKE ? OR n.snippet LIKE ? OR n.publisher LIKE ?
                     ORDER BY n.sort_ts DESC LIMIT 200""", (like, like, like))
    return {"stocks": stocks, "recs": recs, "news": news_df}

"""All write-side SQL lives here. Every statement is parameterized."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from database.connection import transaction
from utils.timeutils import UTC, now_iso, parse_datetime, to_iso


@dataclass
class FoEntry:
    symbol: str
    underlying: str
    lot_size: int | None


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------------------------------------------------------------- app state
    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ---------------------------------------------------------------- stocks / universe
    def apply_fo_universe(self, entries: Sequence[FoEntry], as_of: date) -> dict[str, Any]:
        """Upsert the current F&O list; mark stocks that dropped out as inactive."""
        today = as_of.isoformat()
        now = now_iso()
        with transaction(self.conn):
            first_load = self.conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0] == 0
            active_before = {r["symbol"] for r in self.conn.execute("SELECT symbol FROM stocks WHERE is_fo_active = 1")}
            current = {e.symbol for e in entries}
            added = sorted(current - active_before)
            removed = sorted(active_before - current)
            for e in entries:
                self.conn.execute(
                    """INSERT INTO stocks(symbol, name, is_fo_active, fo_lot_size, fo_added_on, last_seen_in_fo_list, updated_at)
                       VALUES (?, ?, 1, ?, ?, ?, ?)
                       ON CONFLICT(symbol) DO UPDATE SET
                         is_fo_active = 1, fo_lot_size = excluded.fo_lot_size, fo_removed_on = NULL,
                         fo_added_on = CASE WHEN stocks.is_fo_active = 0 THEN excluded.fo_added_on ELSE stocks.fo_added_on END,
                         last_seen_in_fo_list = excluded.last_seen_in_fo_list, updated_at = excluded.updated_at""",
                    (e.symbol, e.underlying, e.lot_size, None if first_load else today, today, now),
                )
            for symbol in removed:
                self.conn.execute(
                    "UPDATE stocks SET is_fo_active = 0, fo_removed_on = ?, updated_at = ? WHERE symbol = ?",
                    (today, now, symbol),
                )
        return {"total": len(current), "added": [] if first_load else added, "removed": removed}

    def update_reference_data(self, ref: dict[str, dict[str, str]]) -> int:
        """ref: symbol -> {name, sector, isin} from NSE index constituent files."""
        count = 0
        with transaction(self.conn):
            for symbol, info in ref.items():
                cur = self.conn.execute(
                    "UPDATE stocks SET name = COALESCE(?, name), sector = COALESCE(?, sector), isin = COALESCE(?, isin), updated_at = ? WHERE symbol = ?",
                    (info.get("name"), info.get("sector"), info.get("isin"), now_iso(), symbol),
                )
                count += cur.rowcount
        return count

    def active_stocks(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM stocks WHERE is_fo_active = 1 ORDER BY symbol").fetchall()

    def stock_by_symbol(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM stocks WHERE symbol = ?", (symbol,)).fetchone()

    def symbol_to_id(self) -> dict[str, int]:
        return {r["symbol"]: r["id"] for r in self.conn.execute("SELECT id, symbol FROM stocks")}

    def replace_aliases(self, aliases: dict[int, list[tuple[str, str]]]) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM stock_aliases")
            self.conn.executemany(
                "INSERT OR IGNORE INTO stock_aliases(stock_id, alias, alias_type) VALUES (?, ?, ?)",
                [(sid, alias, kind) for sid, items in aliases.items() for alias, kind in items],
            )

    def alias_rows(self) -> list[tuple[int, str, str, str]]:
        rows = self.conn.execute(
            """SELECT a.stock_id, s.symbol, a.alias, a.alias_type FROM stock_aliases a
               JOIN stocks s ON s.id = a.stock_id WHERE s.is_fo_active = 1"""
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    # ---------------------------------------------------------------- prices
    def upsert_prices(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        with transaction(self.conn):
            self.conn.executemany(
                """INSERT INTO price_history(stock_id, trade_date, open, high, low, close, prev_close, volume, source)
                   VALUES (:stock_id, :trade_date, :open, :high, :low, :close, :prev_close, :volume, :source)
                   ON CONFLICT(stock_id, trade_date) DO UPDATE SET open=excluded.open, high=excluded.high,
                     low=excluded.low, close=excluded.close, prev_close=excluded.prev_close,
                     volume=excluded.volume, source=excluded.source""",
                rows,
            )
        return len(rows)

    def upsert_index_levels(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        with transaction(self.conn):
            self.conn.executemany(
                """INSERT INTO index_levels(index_name, trade_date, close, change, change_pct, source)
                   VALUES (:index_name, :trade_date, :close, :change, :change_pct, :source)
                   ON CONFLICT(index_name, trade_date) DO UPDATE SET close=excluded.close,
                     change=excluded.change, change_pct=excluded.change_pct, source=excluded.source""",
                rows,
            )
        return len(rows)

    def upsert_fo_activity(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        with transaction(self.conn):
            self.conn.executemany(
                """INSERT OR REPLACE INTO fo_activity(stock_id, trade_date, fut_oi, opt_oi, total_oi, oi_contracts,
                       oi_change, fut_contracts, opt_contracts, total_contracts, turnover, underlying_price, lot_size, source)
                   VALUES (:stock_id, :trade_date, :fut_oi, :opt_oi, :total_oi, :oi_contracts, :oi_change,
                       :fut_contracts, :opt_contracts, :total_contracts, :turnover, :underlying_price, :lot_size, :source)""",
                rows,
            )
        return len(rows)

    def upsert_technical_signals(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        with transaction(self.conn):
            self.conn.executemany(
                """INSERT OR REPLACE INTO technical_signals(stock_id, timeframe, bar_time, computed_at, close, rsi, adx,
                       supertrend, ema20, vwap, rsi_state, adx_ok, above_supertrend, above_ema20, above_vwap, setup, data_source)
                   VALUES (:stock_id, :timeframe, :bar_time, :computed_at, :close, :rsi, :adx, :supertrend, :ema20, :vwap,
                       :rsi_state, :adx_ok, :above_supertrend, :above_ema20, :above_vwap, :setup, :data_source)""",
                rows,
            )
        return len(rows)

    def _replace_rows(self, table: str, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = list(rows[0])
        sql = f"INSERT OR REPLACE INTO {table}({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
        with transaction(self.conn):
            self.conn.executemany(sql, rows)
        return len(rows)

    def upsert_fundamentals(self, rows: list[dict[str, Any]]) -> int:
        return self._replace_rows("fundamentals", rows)

    def upsert_intraday_snapshot(self, rows: list[dict[str, Any]]) -> int:
        return self._replace_rows("intraday_snapshot", rows)

    def upsert_intraday_index(self, rows: list[dict[str, Any]]) -> int:
        return self._replace_rows("intraday_index", rows)

    def insert_market_snapshot(self, taken_at: str, payload: str, ai_summary: str | None, ai_model: str | None) -> int:
        cur = self.conn.execute("INSERT INTO market_snapshots(taken_at, payload, ai_summary, ai_model) VALUES (?, ?, ?, ?)",
                                (taken_at, payload, ai_summary, ai_model))
        return int(cur.lastrowid)

    def avg_daily_volume(self, days: int = 20) -> dict[int, float]:
        rows = self.conn.execute(
            """SELECT stock_id, AVG(volume) FROM (
                 SELECT stock_id, volume, ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY trade_date DESC) rn
                 FROM price_history) WHERE rn <= ? GROUP BY stock_id""", (days,)).fetchall()
        return {r[0]: r[1] for r in rows if r[1]}

    def price_frame_rows(self, stock_id: int, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT trade_date, open, high, low, close, volume FROM price_history
               WHERE stock_id = ? ORDER BY trade_date DESC LIMIT ?""", (stock_id, limit)
        ).fetchall()

    def price_dates(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT DISTINCT trade_date FROM price_history")}

    def index_dates(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT DISTINCT trade_date FROM index_levels")}

    def official_index_prev_close(self, session_date: str) -> dict[str, float]:
        """NSE close of each index on the last trading day before `session_date`."""
        return {r[0]: r[1] for r in self.conn.execute(
            """SELECT index_name, close FROM (
                 SELECT index_name, close, ROW_NUMBER() OVER (PARTITION BY index_name ORDER BY trade_date DESC) rn
                 FROM index_levels WHERE trade_date < ? AND close IS NOT NULL) WHERE rn = 1""", (session_date,))}

    def official_stock_prev_close(self, session_date: str) -> dict[int, float]:
        """NSE bhavcopy close of each stock on the last trading day before `session_date`."""
        return {r[0]: r[1] for r in self.conn.execute(
            """SELECT stock_id, close FROM (
                 SELECT stock_id, close, ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY trade_date DESC) rn
                 FROM price_history WHERE trade_date < ? AND close IS NOT NULL) WHERE rn = 1""", (session_date,))}

    def latest_close(self, stock_id: int) -> tuple[float | None, str | None]:
        row = self.conn.execute(
            "SELECT close, trade_date FROM price_history WHERE stock_id = ? ORDER BY trade_date DESC LIMIT 1", (stock_id,)
        ).fetchone()
        return (row["close"], row["trade_date"]) if row else (None, None)

    # ---------------------------------------------------------------- sources & logs
    def sync_sources(self, configs: Iterable[Any]) -> None:
        with transaction(self.conn):
            for c in configs:
                self.conn.execute(
                    """INSERT INTO sources(name, publisher, domain, kind, base_url, enabled, is_original_publisher, notes, tos_checked, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(name) DO UPDATE SET publisher=excluded.publisher, domain=excluded.domain,
                         kind=excluded.kind, base_url=excluded.base_url, enabled=excluded.enabled,
                         is_original_publisher=excluded.is_original_publisher, notes=excluded.notes,
                         tos_checked=excluded.tos_checked,
                         status=CASE WHEN excluded.enabled = 0 THEN 'DISABLED'
                                     WHEN sources.status = 'DISABLED' THEN 'NEVER_RUN' ELSE sources.status END""",
                    (c.name, c.publisher, c.domain, c.type, c.feeds[0] if c.feeds else None, int(c.enabled),
                     int(c.is_original_publisher), c.notes, c.tos_checked, "NEVER_RUN" if c.enabled else "DISABLED"),
                )

    def get_source(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()

    def ensure_source(self, name: str, kind: str, publisher: str | None = None) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO sources(name, kind, publisher, enabled, status) VALUES (?, ?, ?, 1, 'NEVER_RUN')",
            (name, kind, publisher or name),
        )
        return self.conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()[0]

    def record_source_result(self, source_id: int, status: str, *, error: str | None = None,
                             success: bool = False, next_allowed: datetime | None = None) -> None:
        now = now_iso()
        if success:
            self.conn.execute(
                """UPDATE sources SET status=?, last_attempt_at=?, last_success_at=?, last_error=NULL,
                   consecutive_failures=0, next_allowed_fetch_at=NULL WHERE id=?""",
                (status, now, now, source_id),
            )
        else:
            self.conn.execute(
                """UPDATE sources SET status=?, last_attempt_at=?, last_error=?,
                   consecutive_failures=consecutive_failures+1, next_allowed_fetch_at=? WHERE id=?""",
                (status, now, (error or "")[:2000], to_iso(next_allowed), source_id),
            )

    def log_fetch(self, **fields: Any) -> None:
        cols = ", ".join(fields)
        marks = ", ".join(f":{k}" for k in fields)
        self.conn.execute(f"INSERT INTO fetch_logs({cols}) VALUES ({marks})", fields)

    # ---------------------------------------------------------------- news
    def news_url_exists(self, url_hash: str) -> bool:
        return self.conn.execute("SELECT 1 FROM news WHERE url_hash = ?", (url_hash,)).fetchone() is not None

    def same_story_same_publisher(self, content_hash: str, publisher: str, since_iso: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM news WHERE content_hash = ? AND publisher = ? AND sort_ts >= ? LIMIT 1",
            (content_hash, publisher, since_iso),
        ).fetchone() is not None

    def recent_headlines(self, since_iso: str) -> list[tuple[int, str, str, int | None]]:
        rows = self.conn.execute(
            "SELECT id, headline, content_hash, story_cluster_id FROM news WHERE sort_ts >= ?", (since_iso,)
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def insert_news(self, item: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """INSERT INTO news(source_id, publisher, headline, snippet, url, canonical_url, url_hash, content_hash,
                   story_cluster_id, category, category_method, published_at, retrieved_at, sort_ts)
               VALUES (:source_id, :publisher, :headline, :snippet, :url, :canonical_url, :url_hash, :content_hash,
                   :story_cluster_id, :category, :category_method, :published_at, :retrieved_at, :sort_ts)""",
            item,
        )
        news_id = int(cur.lastrowid)
        if item.get("story_cluster_id") is None:
            self.conn.execute("UPDATE news SET story_cluster_id = ? WHERE id = ?", (news_id, news_id))
        return news_id

    def link_news_stocks(self, news_id: int, stock_ids: Iterable[int], method: str) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO news_stocks(news_id, stock_id, match_method) VALUES (?, ?, ?)",
            [(news_id, sid, method) for sid in stock_ids],
        )

    def purge_old_snippets(self, days: int) -> int:
        cutoff = to_iso(datetime.now(UTC) - timedelta(days=days))
        return self.conn.execute("UPDATE news SET snippet = NULL WHERE sort_ts < ? AND snippet IS NOT NULL", (cutoff,)).rowcount

    # ---------------------------------------------------------------- brokerages / analysts
    def brokerage_id(self, name: str | None) -> int | None:
        if not name:
            return None
        self.conn.execute("INSERT OR IGNORE INTO brokerages(canonical_name) VALUES (?)", (name,))
        return self.conn.execute("SELECT id FROM brokerages WHERE canonical_name = ?", (name,)).fetchone()[0]

    def analyst_id(self, name: str | None, brokerage_id: int | None) -> int | None:
        if not name:
            return None
        self.conn.execute("INSERT OR IGNORE INTO analysts(name, brokerage_id) VALUES (?, ?)", (name, brokerage_id))
        row = self.conn.execute(
            "SELECT id FROM analysts WHERE name = ? AND IFNULL(brokerage_id, 0) = IFNULL(?, 0)", (name, brokerage_id)
        ).fetchone()
        return row[0]

    # ---------------------------------------------------------------- recommendations
    def find_matching_recommendation(self, stock_id: int, brokerage_id: int | None, analyst_id: int | None,
                                     action: str, published_at: str, target: float | None,
                                     window_days: int = 3) -> sqlite3.Row | None:
        """Same call reported again (by another outlet or a later article): same stock, same
        brokerage/analyst, same normalized action, within +/- window_days, and no conflicting target."""
        if brokerage_id is None and analyst_id is None:
            return None  # cannot prove two unattributed calls are the same
        pub = parse_datetime(published_at, assume_tz=UTC)
        lo, hi = to_iso(pub - timedelta(days=window_days)), to_iso(pub + timedelta(days=window_days))
        candidates = self.conn.execute(
            """SELECT * FROM recommendations WHERE stock_id = ? AND normalized_action = ?
                 AND IFNULL(brokerage_id, 0) = IFNULL(?, 0)
                 AND (? IS NULL OR analyst_id IS NULL OR analyst_id = ?)
                 AND published_at BETWEEN ? AND ?
               ORDER BY published_at DESC""",
            (stock_id, action, brokerage_id, analyst_id, analyst_id, lo, hi),
        ).fetchall()
        for row in candidates:
            existing = row["target_price"]
            if target is None or existing is None or abs(existing - target) <= 0.005 * max(existing, target):
                return row
        return None

    def insert_recommendation(self, rec: dict[str, Any]) -> int:
        self.conn.execute(
            """INSERT OR IGNORE INTO recommendations(stock_id, symbol, original_action, normalized_action, rating_change,
                   analyst_id, brokerage_id, target_price, target_text, stop_loss, price_at_reco,
                   time_horizon_original, time_horizon, published_at, source_name, source_url, article_url,
                   retrieved_at, extraction_method, evidence_text, confidence, review_note, dedup_key)
               VALUES (:stock_id, :symbol, :original_action, :normalized_action, :rating_change,
                   :analyst_id, :brokerage_id, :target_price, :target_text, :stop_loss, :price_at_reco,
                   :time_horizon_original, :time_horizon, :published_at, :source_name, :source_url, :article_url,
                   :retrieved_at, :extraction_method, :evidence_text, :confidence, :review_note, :dedup_key)""",
            rec,
        )
        return self.conn.execute("SELECT id FROM recommendations WHERE dedup_key = ?", (rec["dedup_key"],)).fetchone()[0]

    def fill_missing_recommendation_fields(self, rec_id: int, rec: dict[str, Any]) -> None:
        """A later report of the same call may carry details the first one lacked. Only NULLs are filled."""
        self.conn.execute(
            """UPDATE recommendations SET
                 analyst_id = COALESCE(analyst_id, :analyst_id),
                 target_price = COALESCE(target_price, :target_price),
                 target_text = COALESCE(target_text, :target_text),
                 stop_loss = COALESCE(stop_loss, :stop_loss),
                 price_at_reco = COALESCE(price_at_reco, :price_at_reco),
                 time_horizon_original = COALESCE(time_horizon_original, :time_horizon_original),
                 time_horizon = CASE WHEN time_horizon_original IS NULL THEN :time_horizon ELSE time_horizon END,
                 rating_change = CASE WHEN rating_change IS NULL OR rating_change = 'N/A' THEN :rating_change ELSE rating_change END
               WHERE id = :id""",
            {**rec, "id": rec_id},
        )

    def add_mention(self, rec_id: int, news_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO recommendation_mentions(recommendation_id, news_id) VALUES (?, ?)", (rec_id, news_id)
        )
        # The earliest report found is treated as the original source for display.
        rows = self.conn.execute(
            """SELECT m.id, n.publisher, n.url, n.sort_ts, s.base_url FROM recommendation_mentions m
               JOIN news n ON n.id = m.news_id JOIN sources s ON s.id = n.source_id
               WHERE m.recommendation_id = ? ORDER BY n.sort_ts ASC, m.id ASC""",
            (rec_id,),
        ).fetchall()
        if not rows:
            return
        first = rows[0]
        self.conn.execute("UPDATE recommendation_mentions SET is_original_source = (id = ?) WHERE recommendation_id = ?",
                          (first["id"], rec_id))
        self.conn.execute(
            """UPDATE recommendations SET source_name = ?, source_url = ?, article_url = ?,
                 published_at = MIN(published_at, ?) WHERE id = ?""",
            (first["publisher"], first["base_url"], first["url"], first["sort_ts"], rec_id),
        )

    def set_recommendations_flag(self, rec_ids: Sequence[int], flagged: bool) -> None:
        self.conn.executemany("UPDATE recommendations SET is_flagged = ? WHERE id = ?",
                              [(int(flagged), rid) for rid in rec_ids])

    # ---------------------------------------------------------------- watchlist
    def watchlist_add(self, stock_id: int) -> None:
        now = now_iso()
        self.conn.execute(
            "INSERT OR IGNORE INTO watchlist(stock_id, added_at, last_viewed_at) VALUES (?, ?, ?)", (stock_id, now, now)
        )

    def watchlist_remove(self, stock_id: int) -> None:
        self.conn.execute("DELETE FROM watchlist WHERE stock_id = ?", (stock_id,))

    def watchlist_mark_seen(self, stock_id: int | None = None) -> None:
        if stock_id is None:
            self.conn.execute("UPDATE watchlist SET last_viewed_at = ?", (now_iso(),))
        else:
            self.conn.execute("UPDATE watchlist SET last_viewed_at = ? WHERE stock_id = ?", (now_iso(), stock_id))

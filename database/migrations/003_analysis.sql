-- Fundamentals (Yahoo Finance via yfinance; unofficial, refreshed daily). Ratios as published by the provider.
CREATE TABLE fundamentals (
    stock_id         INTEGER PRIMARY KEY REFERENCES stocks(id) ON DELETE CASCADE,
    pe               REAL,
    pb               REAL,
    roe              REAL,      -- fraction (0.14 = 14%)
    debt_to_equity   REAL,
    market_cap       REAL,      -- rupees
    earnings_growth  REAL,      -- quarterly YoY, fraction
    revenue_growth   REAL,      -- fraction
    profit_margin    REAL,      -- fraction
    dividend_yield   REAL,      -- percent as reported
    beta             REAL,
    high_52w         REAL,
    low_52w          REAL,
    updated_at       TEXT NOT NULL,
    source           TEXT NOT NULL
);

-- Latest intraday state per stock, computed from closed 5-minute bars.
CREATE TABLE intraday_snapshot (
    stock_id        INTEGER PRIMARY KEY REFERENCES stocks(id) ON DELETE CASCADE,
    session_date    TEXT NOT NULL,
    bar_time        TEXT NOT NULL,
    last            REAL,
    day_open        REAL,
    day_high        REAL,
    day_low         REAL,
    prev_close      REAL,
    change_pct      REAL,
    day_volume      REAL,
    avg_volume_20d  REAL,
    relative_volume REAL,       -- today's volume vs time-adjusted 20-day average
    vwap            REAL,
    orb_high        REAL,       -- opening range (first 15 minutes)
    orb_low         REAL,
    orb_status      TEXT,       -- ABOVE_ORB | BELOW_ORB | INSIDE
    computed_at     TEXT NOT NULL,
    source          TEXT NOT NULL
);

CREATE TABLE intraday_index (
    index_name   TEXT PRIMARY KEY,
    session_date TEXT NOT NULL,
    bar_time     TEXT NOT NULL,
    last         REAL,
    prev_close   REAL,
    change_pct   REAL,
    day_high     REAL,
    day_low      REAL,
    computed_at  TEXT NOT NULL,
    source       TEXT NOT NULL
);

-- Hourly market analysis snapshots (facts computed from stored data; JSON payload).
CREATE TABLE market_snapshots (
    id          INTEGER PRIMARY KEY,
    taken_at    TEXT NOT NULL,
    payload     TEXT NOT NULL,
    ai_summary  TEXT,
    ai_model    TEXT
);
CREATE INDEX ix_market_snapshots_taken ON market_snapshots(taken_at DESC);

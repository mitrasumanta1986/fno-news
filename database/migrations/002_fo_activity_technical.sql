-- Per-underlying aggregates from the NSE F&O bhavcopy (EOD).
CREATE TABLE fo_activity (
    stock_id          INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    trade_date        TEXT NOT NULL,
    fut_oi            REAL,     -- open interest in shares
    opt_oi            REAL,
    total_oi          REAL,
    oi_contracts      REAL,     -- total_oi / lot size
    oi_change         REAL,     -- change in OI (shares)
    fut_contracts     REAL,     -- traded contracts
    opt_contracts     REAL,
    total_contracts   REAL,
    turnover          REAL,     -- notional traded value, rupees
    underlying_price  REAL,
    lot_size          INTEGER,
    source            TEXT NOT NULL,
    PRIMARY KEY (stock_id, trade_date)
);
CREATE INDEX ix_fo_activity_date ON fo_activity(trade_date);

-- Latest indicator snapshot per stock and timeframe. These are indicator CONDITIONS,
-- not recommendations.
CREATE TABLE technical_signals (
    stock_id       INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    timeframe      TEXT NOT NULL,          -- '5m' | '1d'
    bar_time       TEXT NOT NULL,          -- last CLOSED bar used (UTC ISO)
    computed_at    TEXT NOT NULL,
    close          REAL,
    rsi            REAL,
    adx            REAL,
    supertrend     REAL,
    ema20          REAL,
    vwap           REAL,
    rsi_state      TEXT,                   -- BULLISH (>upper) | BEARISH (<lower) | NEUTRAL
    adx_ok         INTEGER,
    above_supertrend INTEGER,
    above_ema20    INTEGER,
    above_vwap     INTEGER,                -- NULL when VWAP not applicable (daily)
    setup          TEXT NOT NULL,          -- BULLISH | BEARISH | NONE
    data_source    TEXT NOT NULL,
    PRIMARY KEY (stock_id, timeframe)
);

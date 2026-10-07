-- All timestamps are UTC ISO-8601 strings ("YYYY-MM-DDTHH:MM:SS+00:00"); dates are "YYYY-MM-DD".
-- NULL means "not published by the source" and is displayed as N/A.

CREATE TABLE stocks (
    id                    INTEGER PRIMARY KEY,
    symbol                TEXT NOT NULL UNIQUE,
    name                  TEXT NOT NULL,
    isin                  TEXT,
    sector                TEXT,
    is_fo_active          INTEGER NOT NULL DEFAULT 0,
    fo_lot_size           INTEGER,
    fo_added_on           TEXT,
    fo_removed_on         TEXT,
    last_seen_in_fo_list  TEXT,
    updated_at            TEXT NOT NULL
);

CREATE TABLE stock_aliases (
    id          INTEGER PRIMARY KEY,
    stock_id    INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    alias_type  TEXT NOT NULL,              -- NAME | CURATED | SYMBOL
    UNIQUE (stock_id, alias)
);

CREATE TABLE sources (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL UNIQUE,
    publisher              TEXT,
    domain                 TEXT,
    kind                   TEXT,
    base_url               TEXT,
    enabled                INTEGER NOT NULL DEFAULT 1,
    is_original_publisher  INTEGER NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL DEFAULT 'NEVER_RUN',
    last_attempt_at        TEXT,
    last_success_at        TEXT,
    last_error             TEXT,
    consecutive_failures   INTEGER NOT NULL DEFAULT 0,
    next_allowed_fetch_at  TEXT,
    notes                  TEXT,
    tos_checked            TEXT
);

CREATE TABLE brokerages (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE
);

CREATE TABLE analysts (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    brokerage_id  INTEGER REFERENCES brokerages(id)
);
CREATE UNIQUE INDEX ux_analysts_name_brokerage ON analysts(name, IFNULL(brokerage_id, 0));

CREATE TABLE news (
    id                INTEGER PRIMARY KEY,
    source_id         INTEGER NOT NULL REFERENCES sources(id),
    publisher         TEXT NOT NULL,
    headline          TEXT NOT NULL,
    snippet           TEXT,
    url               TEXT NOT NULL,
    canonical_url     TEXT NOT NULL,
    url_hash          TEXT NOT NULL UNIQUE,
    content_hash      TEXT NOT NULL,
    story_cluster_id  INTEGER,
    category          TEXT NOT NULL,
    category_method   TEXT NOT NULL DEFAULT 'RULE',
    published_at      TEXT,
    retrieved_at      TEXT NOT NULL,
    sort_ts           TEXT NOT NULL,        -- COALESCE(published_at, retrieved_at)
    ai_summary        TEXT,
    ai_model          TEXT
);
CREATE INDEX ix_news_sort_ts ON news(sort_ts DESC);
CREATE INDEX ix_news_content_hash ON news(content_hash);
CREATE INDEX ix_news_category ON news(category);
CREATE INDEX ix_news_cluster ON news(story_cluster_id);

CREATE TABLE news_stocks (
    news_id       INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    stock_id      INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    match_method  TEXT NOT NULL,
    PRIMARY KEY (news_id, stock_id)
);
CREATE INDEX ix_news_stocks_stock ON news_stocks(stock_id);

CREATE TABLE recommendations (
    id                     INTEGER PRIMARY KEY,
    stock_id               INTEGER NOT NULL REFERENCES stocks(id),
    symbol                 TEXT NOT NULL,
    original_action        TEXT NOT NULL,
    normalized_action      TEXT NOT NULL,
    rating_change          TEXT,
    analyst_id             INTEGER REFERENCES analysts(id),
    brokerage_id           INTEGER REFERENCES brokerages(id),
    target_price           REAL,
    target_text            TEXT,
    stop_loss              REAL,
    price_at_reco          REAL,            -- CMP quoted BY THE SOURCE (not our price feed)
    time_horizon_original  TEXT,
    time_horizon           TEXT,
    published_at           TEXT NOT NULL,
    source_name            TEXT,            -- publisher of the earliest article found
    source_url             TEXT,
    article_url            TEXT,
    retrieved_at           TEXT NOT NULL,
    extraction_method      TEXT NOT NULL,   -- RULE | AI | MANUAL
    evidence_text          TEXT NOT NULL,   -- verbatim text the recommendation was read from
    confidence             REAL,
    review_note            TEXT,
    is_flagged             INTEGER NOT NULL DEFAULT 0,
    dedup_key              TEXT NOT NULL UNIQUE
);
CREATE INDEX ix_recs_stock ON recommendations(stock_id, published_at DESC);
CREATE INDEX ix_recs_published ON recommendations(published_at DESC);

CREATE TABLE recommendation_mentions (
    id                  INTEGER PRIMARY KEY,
    recommendation_id   INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
    news_id             INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    is_original_source  INTEGER NOT NULL DEFAULT 0,  -- earliest report found
    UNIQUE (recommendation_id, news_id)
);

CREATE TABLE watchlist (
    id              INTEGER PRIMARY KEY,
    stock_id        INTEGER NOT NULL UNIQUE REFERENCES stocks(id) ON DELETE CASCADE,
    added_at        TEXT NOT NULL,
    last_viewed_at  TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE price_history (
    stock_id    INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    trade_date  TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    prev_close  REAL,
    volume      INTEGER,
    source      TEXT NOT NULL,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE TABLE index_levels (
    index_name  TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    close       REAL,
    change      REAL,
    change_pct  REAL,
    source      TEXT NOT NULL,
    PRIMARY KEY (index_name, trade_date)
);

CREATE TABLE fetch_logs (
    id                INTEGER PRIMARY KEY,
    source_id         INTEGER REFERENCES sources(id),
    job               TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT NOT NULL,
    items_fetched     INTEGER DEFAULT 0,
    items_new         INTEGER DEFAULT 0,
    items_duplicate   INTEGER DEFAULT 0,
    items_irrelevant  INTEGER DEFAULT 0,
    recs_extracted    INTEGER DEFAULT 0,
    error             TEXT,
    duration_ms       INTEGER
);
CREATE INDEX ix_fetch_logs_started ON fetch_logs(started_at DESC);

CREATE TABLE app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

# Indian F&O News & Research Dashboard

A Streamlit dashboard covering **every current NSE stock-F&O security** (dynamic universe, 210 stocks as of
28-Sep-2026). It aggregates public Indian market news and **brokerage/analyst recommendations exactly as published**,
plus NSE end-of-day data, F&O activity, fundamentals, a technical screen and hourly market analysis.

> **Research aggregator only.** It never makes its own BUY/SELL/HOLD recommendation, has no broker connection
> (no Zerodha/Dhan/Upstox/…), places no trades and generates no orders. Ratings shown are those published by the
> named third party, always with the original wording, evidence text and a link to the source. The technical,
> intraday and scorecard sections show *indicator conditions / descriptive readings*, never trade calls.

## Quick start (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env            # set CONTACT_EMAIL (sent in the User-Agent)

.\.venv\Scripts\python worker.py --once          # first load: universe, 60-day EOD backfill, news, technicals,
                                                 # fundamentals, market snapshot (~15-20 min, throttled)
.\.venv\Scripts\python worker.py                 # keep running: the scheduler (leave this window open)
.\.venv\Scripts\streamlit run app.py             # in a second window -> http://localhost:8501
```

Run a single job: `python worker.py --once --job news|universe|prices|technical|fundamentals|market|maintenance`
(`--source "CNBC-TV18"` limits the news job to one source). Tests: `pip install -r requirements-dev.txt; pytest`.

## Dashboard sections

| Page | What it shows |
|---|---|
| Market Overview | NIFTY 50, BANK NIFTY, FINNIFTY, Midcap Select, Next 50, VIX, sector indices (NSE EOD); latest news; new-recommendation counts; last refresh times |
| All F&O Stocks | Searchable/filterable table of the full universe: price, sector, F&O status, lot, latest news, latest published rating, brokerage, analyst, target, stop loss, horizon, date, source link |
| Latest News | 18 categories (Brokerage Research, Results, Order Win, M&A, FII/DII, …); same story from several outlets collapsed |
| Brokerage Recommendations | Published ratings with original + normalized wording, upside/downside vs last close, evidence text, every article that reported the call, flag-as-incorrect |
| Stock Detail | Price, F&O status, recommendation history + target chart, latest & historical news, F&O activity, technical snapshot, watchlist toggle, optional AI headline digest |
| Published Research Summary | Per-stock counts of BUY / SELL / HOLD / ACCUMULATE / REDUCE / NEUTRAL publications (latest call per brokerage by default) with drill-down to sources |
| **Market Analysis (hourly)** | Rebuilt every hour 09:00–16:00 IST: indices, breadth, VWAP/ORB breadth, sectors, VIX, setup counts, news flow, rating flow, most-active F&O, hourly timeline. Facts only |
| **F&O Stock Analysis** | Five-factor scorecard per stock — technical, fundamental, liquidity, movement, news — with colour-coded readings and a factor breakdown. No combined verdict |
| **Intraday F&O** | Auto-refreshing: gainers/losers, VWAP position, opening-range (15 min) breaks, relative-volume surges, 5-minute bullish/bearish setups |
| F&O Activity (Top 10) | Highest open interest, volume (contracts) and traded value from the NSE F&O bhavcopy |
| Technical Screen | Bullish: RSI>60, ADX>25, price above Supertrend(10,3), EMA20 and VWAP (5-min). Bearish: the mirror. Daily variant from NSE EOD |
| Search / Watchlist / Source Status | Search by name, symbol, brokerage, analyst, sector, keyword; local watchlist with "new since last visit"; per-source ACTIVE / FAILED / RATE LIMITED / NO DATA / BLOCKED / last success |

## Data sources (access reviewed 28-Sep-2026)

| Source | Route | Status |
|---|---|---|
| NSE | F&O lot file (universe), CM & F&O UDiFF bhavcopies, index closes, index constituent lists (sector), corporate-announcements RSS | Official, used |
| Economic Times | Official RSS (markets, stocks, recos) | Used |
| Moneycontrol | Google-News sitemap declared in its robots.txt (its RSS feeds are stale since 2024) | Used — headline/date/URL only |
| CNBC-TV18 | Official RSS | Used |
| NDTV Profit | Publisher's FeedBurner feed | Used |
| Business Standard, Mint | Official RSS | Used |
| Zee Business | Returns HTTP 403 to all automated requests incl. robots.txt | **Not used** (never circumvented) |
| Financial Express | Feeds disabled by publisher (HTTP 410) | Not used |
| Reuters | No public feed; licensed API only | Not used |
| Investing.com | Terms prohibit automated collection | Not used |
| Google News RSS | robots.txt disallows | Not used |
| Yahoo Finance (`yfinance`) | Unofficial: 5-minute bars, intraday indices, fundamentals | Used, labelled "unofficial, delayed". Set `intraday.provider: none` in `config/technical.yaml` to disable |

Sources are plugins configured in `config/sources.yaml` (`rss`, `news_sitemap`, `nse_announcements`). Re-check
publishers' terms periodically and update `tos_checked`.

### Copyright & access rules enforced in code
* robots.txt is evaluated (RFC 9309 wildcards/longest-match) before **every** request; 401/403 = blocked, never bypassed.
* Honest User-Agent with contact e-mail; per-domain throttling (default 5 s); conditional GET; timeouts on every call; bounded retries.
* Only headline, a ≤300-character publisher snippet, metadata and the URL are stored. Article bodies are never fetched or stored. Snippets are purged after `NEWS_RETENTION_DAYS`.
* Personal research use. Re-publishing aggregated content may need publishers' permission.

## How recommendations are extracted

1. **Rule-based extractor** (`processing/rec_extractor.py`) reads a rating only in explicit contexts — e.g.
   `Buy X; target Rs N: Brokerage`, `Nomura retains 'Buy' on X`, `Jefferies upgrades X to Overweight`,
   `maintains reduce rating on X`. Roundup headlines are split into clauses so one clause's rating never
   leaks onto another stock. Missing fields stay `NULL` → **N/A**; nothing is inferred.
2. **Normalization** (`config/normalization.yaml`, editable): e.g. Accumulate/Add → ACCUMULATE; Market Perform /
   Equal-weight / In-line → NEUTRAL; Outperform/Overweight → BUY; Underperform/Underweight → SELL. Unknown wording
   → UNMAPPED (shown, excluded from summary counts). Original wording is always stored.
3. **De-duplication**: canonical-URL hash, same-publisher headline hash, fuzzy story clustering (RapidFuzz ≥ 90).
   The same call (same stock + brokerage/analyst + rating, ±3 days, compatible target) reported by several outlets is
   **one** recommendation with several `recommendation_mentions`; the earliest report is marked as the source.
4. **Sanity checks** flag (never alter) targets far from the last close or stop losses above price for a BUY.
5. **Optional AI** (`AI_ENABLED=true`, `ANTHROPIC_API_KEY`): extraction fallback where every returned field must
   appear verbatim in the source text (else dropped), plus headline/market digests labelled **AI SUMMARY**.
   Stored with `extraction_method = AI`. Default model `claude-opus-5` (low effort, server-side refusal fallback);
   `AI_MODEL=claude-haiku-4-5` is cheaper for this short-text workload.

## Schedule (worker, IST)

| Job | When |
|---|---|
| News sources | Checked every minute; each source runs on its own interval (10–15 min in market hours, 3× slower otherwise), with exponential backoff on failure and `Retry-After` on 429 |
| Intraday bars, 5-min technicals, intraday snapshot | Every 5 min, 09:15–15:40 Mon–Fri |
| Market analysis snapshot | Every hour on the hour, 09:00–16:00 Mon–Fri |
| EOD prices, index closes, F&O bhavcopy, daily screen | 18:45 / 20:45 / 22:45 Mon–Fri (retries until published) |
| F&O universe + sectors + aliases | 08:00 daily (and at start-up if stale) |
| Fundamentals | 07:30 Mon–Fri |
| Maintenance (snippet purge, log pruning) | 02:30 daily |

Tip: register `worker.py` with Windows Task Scheduler ("At log on", run `.venv\Scripts\python.exe worker.py` in
`E:\news`) so it keeps running.

## Project layout

```
app.py              Streamlit entry (multipage navigation, colour theme)
worker.py           Scheduler / one-shot CLI
config/             settings.py (.env), sources.yaml, normalization.yaml, brokerages.yaml, aliases.yaml, technical.yaml
database/           SQLite connection (WAL), versioned migrations, repository (all SQL, parameterized)
sources/            Source plugins (RSS, news sitemap, NSE announcements) + registry
nse/                F&O universe, sector reference, EOD prices, F&O activity
processing/         cleaning, entity tagging, classifier, recommendation extractor, normalizer, dedup, pipeline, ai/
technical/          indicators (RSI/ADX/Supertrend/EMA/VWAP), screener, intraday snapshot, yfinance provider
analysis/           fundamentals, hourly market snapshot, multi-factor scorecard
jobs/               job orchestration with per-source isolation and fetch logging
dashboard/          queries (cached), components, charts, style, views/
tests/              pytest suite (parsers, extractor golden corpus, pipeline, resilience, AI guardrails, page smoke tests)
data/               app.db, cache/ (downloads), manual/ (drop fo_mktlots.csv here if NSE is unreachable)
logs/               worker.log, app.log, refresh.log (rotating)
```

## Security notes
* Secrets only in `.env` (git-ignored); never logged or shown.
* Streamlit binds to `localhost` (`.streamlit/config.toml`). Add authentication before exposing it on a network.
* External text is rendered as plain text/markdown; only `http(s)` links are rendered; HTML is used only for the
  app's own labels (escaped).
* A test fails if any broker SDK or order-placement code appears in the project.

## Known limitations
* NSE prices/OI are end-of-day. Intraday data comes from Yahoo Finance via `yfinance` (unofficial, delayed, may break).
* Many published calls give no stop loss, analyst or horizon in the headline/snippet; those show N/A by design.
* Headline-based extraction can miss calls or, rarely, mis-read one. Every row shows its evidence text and source link; use **Flag as incorrect** to hide bad rows.
* Fundamentals are the provider's figures and can lag corporate actions.

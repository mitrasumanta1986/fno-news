"""Turns raw source items into stored news, stock tags and recommendations."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from config.settings import Settings, load_yaml
from database.connection import transaction
from database.repository import Repository
from processing.classifier import MARKET_RX, MARKET_WIDE, classify
from processing.cleaning import clean_headline, clean_text, truncate
from processing.dedup import ClusterIndex
from processing.entities import BrokerageMatcher, StockTagger, resolve_entities
from processing.normalizer import Normalizer
from processing.rec_extractor import ExtractedRec, RecommendationExtractor
from sources.base import RawItem
from utils.hashing import canonicalize_url, content_hash, sha256
from utils.timeutils import UTC, now_iso, now_utc, parse_datetime, to_iso

log = logging.getLogger(__name__)


@dataclass
class ProcessingContext:
    settings: Settings
    tagger: StockTagger
    brokers: BrokerageMatcher
    normalizer: Normalizer
    extractor: RecommendationExtractor
    ai: Any = None  # optional processing.ai.AIAssistant


def build_context(repo: Repository, settings: Settings) -> ProcessingContext:
    tagger = StockTagger(repo.alias_rows())
    brokers = BrokerageMatcher(load_yaml("brokerages.yaml").get("brokerages", {}))
    normalizer = Normalizer(load_yaml("normalization.yaml"))
    ai = None
    if settings.ai_enabled:
        try:
            from processing.ai.assistant import AIAssistant
            ai = AIAssistant(settings)
        except Exception as exc:  # AI is optional; never block ingestion
            log.warning("AI assistant unavailable: %s", exc)
    return ProcessingContext(settings, tagger, brokers, normalizer, RecommendationExtractor(tagger, brokers, normalizer), ai)


def process_items(repo: Repository, source_id: int, items: list[RawItem], ctx: ProcessingContext) -> dict[str, int]:
    stats = {"fetched": len(items), "new": 0, "duplicate": 0, "irrelevant": 0, "recs": 0, "errors": 0}
    since = to_iso(now_utc() - timedelta(hours=72))
    clusters = ClusterIndex(repo.recent_headlines(since))
    for raw in items:
        try:
            outcome = _process_one(repo, source_id, raw, ctx, clusters)
            stats[outcome[0]] += 1
            stats["recs"] += outcome[1]
        except sqlite3.Error:
            raise  # database problems are not per-item problems
        except Exception:
            stats["errors"] += 1
            log.exception("failed to process item %r", raw.url)
    return stats


def _process_one(repo: Repository, source_id: int, raw: RawItem, ctx: ProcessingContext,
                 clusters: ClusterIndex) -> tuple[str, int]:
    headline = clean_headline(raw.title)
    if not headline or not raw.url.startswith(("http://", "https://")):
        return "irrelevant", 0
    canonical = canonicalize_url(raw.url)
    uhash = sha256(canonical)
    if repo.news_url_exists(uhash):
        return "duplicate", 0
    chash = content_hash(headline)
    retrieved = now_iso()
    published = to_iso(raw.published) if raw.published else None
    if published and published > retrieved:
        published = retrieved  # clock skew / future-dated feed entries
    sort_ts = published or retrieved
    week_ago = to_iso(parse_datetime(sort_ts, assume_tz=UTC) - timedelta(days=7))
    if repo.same_story_same_publisher(chash, raw.publisher, week_ago):
        return "duplicate", 0

    snippet = truncate(clean_text(raw.summary), ctx.settings.snippet_max_chars)
    full_text = f"{headline}. {snippet or ''}"
    stocks, brokers = resolve_entities(ctx.tagger.find(full_text), ctx.brokers.find(full_text))
    recs = ctx.extractor.extract(headline, snippet)
    if not recs and ctx.ai is not None and ctx.ai.should_try(full_text, stocks):
        recs = ctx.ai.extract_recommendations(headline, snippet, ctx)
    stock_ids = {s.stock_id for s in stocks} | {r.stock_id for r in recs}

    category = classify(full_text, has_recommendation=bool(recs), has_brokerage=bool(brokers),
                        rec_has_brokerage=any(r.brokerage for r in recs))
    if not stock_ids and not (category in MARKET_WIDE and MARKET_RX.search(full_text)):
        return "irrelevant", 0

    cluster_id = clusters.find(headline, chash)
    with transaction(repo.conn):
        news_id = repo.insert_news({
            "source_id": source_id, "publisher": raw.publisher, "headline": headline, "snippet": snippet,
            "url": raw.url, "canonical_url": canonical, "url_hash": uhash, "content_hash": chash,
            "story_cluster_id": cluster_id, "category": category, "category_method": "RULE",
            "published_at": published, "retrieved_at": retrieved, "sort_ts": sort_ts,
        })
        repo.link_news_stocks(news_id, stock_ids, "ALIAS")
        for rec in recs:
            _persist_recommendation(repo, rec, news_id, sort_ts, retrieved)
    clusters.add(cluster_id or news_id, headline, chash)
    return "new", len(recs)


def _persist_recommendation(repo: Repository, rec: ExtractedRec, news_id: int, published: str, retrieved: str) -> None:
    brokerage_id = repo.brokerage_id(rec.brokerage)
    analyst_id = repo.analyst_id(rec.analyst, brokerage_id)
    review = []
    close, close_date = repo.latest_close(rec.stock_id)
    if close and rec.target_price and not (0.2 * close <= rec.target_price <= 5 * close):
        review.append(f"Target {rec.target_price:g} is far from last close {close:g} ({close_date}); verify against source")
    if close and rec.stop_loss and rec.normalized_action == "BUY" and rec.stop_loss >= close * 1.02:
        review.append("Stop loss above last close for a BUY; verify against source")
    fields: dict[str, Any] = {
        "stock_id": rec.stock_id, "symbol": rec.symbol, "original_action": rec.original_action,
        "normalized_action": rec.normalized_action, "rating_change": rec.rating_change,
        "analyst_id": analyst_id, "brokerage_id": brokerage_id, "target_price": rec.target_price,
        "target_text": rec.target_text, "stop_loss": rec.stop_loss, "price_at_reco": rec.price_at_reco,
        "time_horizon_original": rec.horizon_original, "time_horizon": rec.horizon, "published_at": published,
        "source_name": None, "source_url": None, "article_url": None, "retrieved_at": retrieved,
        "extraction_method": rec.method, "evidence_text": rec.evidence_text[:1000], "confidence": rec.confidence,
        "review_note": "; ".join(review) or None,
    }
    existing = repo.find_matching_recommendation(rec.stock_id, brokerage_id, analyst_id, rec.normalized_action,
                                                 published, rec.target_price)
    if existing:
        repo.fill_missing_recommendation_fields(existing["id"], fields)
        repo.add_mention(existing["id"], news_id)
        return
    who = f"{brokerage_id or ''}|{analyst_id or ''}"
    fields["dedup_key"] = "|".join([
        rec.symbol, who, rec.normalized_action, f"{rec.target_price or ''}", published[:10],
        f"n{news_id}" if who == "|" else "",
    ])
    rec_id = repo.insert_recommendation(fields)
    repo.add_mention(rec_id, news_id)

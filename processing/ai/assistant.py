"""Optional Claude-based helpers (AI_ENABLED=true and ANTHROPIC_API_KEY set).

Guardrails:
  * The model only sees the publisher's headline/snippet and may only COPY values from it.
  * Every returned field is verified verbatim against the source text; unverifiable fields are
    dropped, and a recommendation without a verifiable rating word + stock is discarded.
  * AI-extracted recommendations are stored with extraction_method = 'AI' and labelled in the UI.
  * Summaries are labelled "AI SUMMARY" and are never stored as recommendations.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from config.settings import Settings
from processing.entities import StockMatch
from processing.rec_extractor import ExtractedRec

if TYPE_CHECKING:
    from processing.pipeline import ProcessingContext

log = logging.getLogger(__name__)

MAX_CALLS_PER_PROCESS = 200  # hard cost cap per worker process lifetime

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_NUM = {"type": ["number", "null"]}
_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "rating_as_written": {"type": "string"},
                    "brokerage_as_written": _NULLABLE_STR,
                    "analyst_as_written": _NULLABLE_STR,
                    "target_price": _NULLABLE_NUM,
                    "stop_loss": _NULLABLE_NUM,
                    "time_horizon_as_written": _NULLABLE_STR,
                    "evidence_quote": {"type": "string"},
                },
                "required": ["company", "rating_as_written", "brokerage_as_written", "analyst_as_written",
                             "target_price", "stop_loss", "time_horizon_as_written", "evidence_quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recommendations"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You extract stock recommendations that are EXPLICITLY published in a news headline/snippet from Indian "
    "financial media. Only report a recommendation when the text itself states a rating (e.g. Buy, Sell, Hold, "
    "Accumulate, Reduce, Neutral, Outperform) attributed to a brokerage, analyst or the publication for a specific "
    "company. Copy every value exactly as written in the text. Use null for anything not stated. Never infer, "
    "estimate or add information. If the text only reports price moves, results or opinions without an explicit "
    "rating, return an empty list. evidence_quote must be an exact substring of the text."
)


def _contains(text: str, fragment: str | None) -> bool:
    if not fragment:
        return False
    norm = lambda s: re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()  # noqa: E731
    return norm(fragment) in norm(text)


def _number_in_text(text: str, value: float | None) -> bool:
    if value is None:
        return False
    numbers = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    return any(abs(n - value) < 0.01 for n in numbers)


class AIAssistant:
    def __init__(self, settings: Settings):
        import anthropic  # optional dependency

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)
        self.model = settings.ai_model
        self._calls = 0
        self._lock = threading.Lock()

    def _budget_ok(self) -> bool:
        with self._lock:
            if self._calls >= MAX_CALLS_PER_PROCESS:
                return False
            self._calls += 1
            return True

    def should_try(self, text: str, stocks: list[StockMatch]) -> bool:
        return bool(stocks) and re.search(
            r"\b(?:buy|sell|hold|accumulate|reduce|neutral|outperform|underperform|overweight|underweight|target)\b",
            text, re.I) is not None

    def _create(self, **kwargs: Any):
        params: dict[str, Any] = {"model": self.model, **kwargs}
        if self.model.startswith(("claude-opus-5", "claude-fable")):
            # Server-side refusal fallback; low effort is plenty for short extraction.
            params.setdefault("output_config", {})["effort"] = "low"
            return self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        return self.client.messages.create(**params)

    def extract_recommendations(self, headline: str, snippet: str | None, ctx: "ProcessingContext") -> list[ExtractedRec]:
        if not self._budget_ok():
            return []
        text = f"{headline}\n{snippet or ''}".strip()
        try:
            response = self._create(
                max_tokens=2000, system=_SYSTEM,
                messages=[{"role": "user", "content": f"<text>\n{text}\n</text>"}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            )
        except self._anthropic.APIError as exc:
            log.warning("AI extraction failed: %s", exc)
            return []
        if response.stop_reason in ("refusal", "max_tokens"):
            return []
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            items = json.loads(raw).get("recommendations", [])
        except (ValueError, AttributeError):
            return []
        return [rec for item in items if (rec := self._verify(item, text, ctx))]

    def _verify(self, item: dict[str, Any], text: str, ctx: "ProcessingContext") -> ExtractedRec | None:
        evidence = item.get("evidence_quote") or ""
        rating = item.get("rating_as_written") or ""
        if not _contains(text, evidence) or not _contains(evidence, rating):
            return None
        normalized = ctx.normalizer.action(rating)
        if normalized == "UNMAPPED":
            return None
        stocks = {s.stock_id: s for s in ctx.tagger.find(evidence)}
        company_stocks = {s.stock_id: s for s in ctx.tagger.find(item.get("company") or "")}
        matched = [s for sid, s in stocks.items() if sid in company_stocks] or list(stocks.values())
        if len({s.stock_id for s in matched}) != 1:
            return None
        stock = matched[0]
        brokerage_text = item.get("brokerage_as_written")
        brokerage = None
        if _contains(text, brokerage_text):
            known = ctx.brokers.find(brokerage_text)
            brokerage = known[0].name if known else brokerage_text.strip()
        analyst = item.get("analyst_as_written") if _contains(text, item.get("analyst_as_written")) else None
        target = item.get("target_price") if _number_in_text(text, item.get("target_price")) else None
        stop_loss = item.get("stop_loss") if _number_in_text(text, item.get("stop_loss")) else None
        horizon_text = item.get("time_horizon_as_written")
        horizon_original, horizon = ctx.normalizer.horizon(horizon_text) if _contains(text, horizon_text) else (None, None)
        if not (brokerage or analyst or target):
            return None
        return ExtractedRec(
            stock_id=stock.stock_id, symbol=stock.symbol, original_action=rating.strip(), normalized_action=normalized,
            brokerage=brokerage, analyst=analyst, target_price=target, stop_loss=stop_loss,
            horizon_original=horizon_original, horizon=horizon, evidence_text=evidence, confidence=0.6, method="AI",
        )

    def summarize_market(self, snapshot: dict[str, Any]) -> str | None:
        """Plain-language digest of the rule-generated market snapshot. Labelled AI SUMMARY in the UI."""
        if not self._budget_ok():
            return None
        facts = json.dumps({k: snapshot.get(k) for k in ("observations", "indices", "breadth", "sectors", "technical",
                                                          "published_ratings_24h", "key_headlines")}, default=str)[:12000]
        try:
            response = self._create(
                max_tokens=1500,
                system=("Write a short, neutral market-status note (4-6 bullet points) for Indian equities using ONLY the "
                        "facts in the JSON provided. Do not predict prices, do not recommend buying or selling anything, "
                        "and do not add facts that are not in the data."),
                messages=[{"role": "user", "content": facts}],
            )
        except self._anthropic.APIError as exc:
            log.warning("AI market summary failed: %s", exc)
            return None
        if response.stop_reason == "refusal":
            return None
        return next((b.text for b in response.content if b.type == "text"), None)

    def summarize_headlines(self, company: str, headlines: list[str]) -> str | None:
        """Neutral digest of recent headlines for one stock. Labelled AI SUMMARY in the UI."""
        if not headlines or not self._budget_ok():
            return None
        listing = "\n".join(f"- {h}" for h in headlines[:40])
        try:
            response = self._create(
                max_tokens=1500,
                system=("Summarize the news headlines provided, neutrally, in 3-5 bullet points. Use only facts in the "
                        "headlines. Do not give investment advice, ratings, price predictions or opinions of your own."),
                messages=[{"role": "user", "content": f"Company: {company}\nHeadlines:\n{listing}"}],
            )
        except self._anthropic.APIError as exc:
            log.warning("AI summary failed: %s", exc)
            return None
        if response.stop_reason == "refusal":
            return None
        return next((b.text for b in response.content if b.type == "text"), None)

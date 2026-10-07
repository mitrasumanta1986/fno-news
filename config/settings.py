"""Application settings: secrets and tunables from .env, rules from YAML files in config/."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
APP_NAME = "FnONewsDashboard"
APP_VERSION = "0.1"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    cache_dir: Path
    manual_dir: Path
    log_dir: Path
    log_level: str
    contact_email: str
    connect_timeout: float
    read_timeout: float
    domain_min_interval: float
    price_backfill_days: int
    snippet_max_chars: int
    news_retention_days: int
    ai_enabled: bool
    ai_model: str
    anthropic_api_key: str | None = field(default=None, repr=False)

    @property
    def user_agent(self) -> str:
        # Honest, identifiable client string. We never impersonate a browser. The contact address goes in the
        # standard `From` header instead: NSE's firewall silently stalls requests with an email in the UA.
        return f"{APP_NAME}/{APP_VERSION} (personal research dashboard)"

    @property
    def robots_agent_token(self) -> str:
        return APP_NAME.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    data_dir = BASE_DIR / "data"
    api_key = os.getenv("ANTHROPIC_API_KEY") or None
    return Settings(
        db_path=_resolve(os.getenv("DB_PATH", "data/app.db")),
        data_dir=data_dir,
        cache_dir=data_dir / "cache",
        manual_dir=data_dir / "manual",
        log_dir=BASE_DIR / "logs",
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        contact_email=os.getenv("CONTACT_EMAIL", "not-configured"),
        connect_timeout=_env_float("HTTP_CONNECT_TIMEOUT", 5.0),
        read_timeout=_env_float("HTTP_READ_TIMEOUT", 20.0),
        domain_min_interval=_env_float("DOMAIN_MIN_INTERVAL_SECONDS", 5.0),
        price_backfill_days=_env_int("PRICE_BACKFILL_DAYS", 60),
        snippet_max_chars=_env_int("SNIPPET_MAX_CHARS", 300),
        news_retention_days=_env_int("NEWS_RETENTION_DAYS", 365),
        ai_enabled=_env_bool("AI_ENABLED") and api_key is not None,
        ai_model=os.getenv("AI_MODEL", "claude-opus-5"),
        anthropic_api_key=api_key,
    )


def load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

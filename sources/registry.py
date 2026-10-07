"""Builds source plugins from config/sources.yaml."""
from __future__ import annotations

from config.settings import Settings, load_yaml
from sources.base import BaseSource, SourceConfig
from sources.news_sitemap import NewsSitemapSource
from sources.nse_announcements import NseAnnouncementsSource
from sources.rss import RssSource
from utils.http import HttpClient

SOURCE_TYPES: dict[str, type[BaseSource]] = {
    "rss": RssSource,
    "news_sitemap": NewsSitemapSource,
    "nse_announcements": NseAnnouncementsSource,
}


def load_source_configs() -> list[SourceConfig]:
    configs = []
    for raw in load_yaml("sources.yaml").get("sources", []):
        if raw.get("type") not in SOURCE_TYPES:
            raise ValueError(f"unknown source type {raw.get('type')!r} for {raw.get('name')!r}")
        configs.append(SourceConfig(
            name=raw["name"], type=raw["type"], publisher=raw.get("publisher", raw["name"]),
            domain=raw.get("domain"), enabled=bool(raw.get("enabled", True)),
            interval_minutes=int(raw.get("interval_minutes", 15)), feeds=list(raw.get("feeds") or []),
            notes=raw.get("notes"), is_original_publisher=bool(raw.get("is_original_publisher", False)),
            tos_checked=str(raw["tos_checked"]) if raw.get("tos_checked") else None,
            options=dict(raw.get("options") or {}),
        ))
    return configs


def build_source(config: SourceConfig, client: HttpClient, settings: Settings) -> BaseSource:
    return SOURCE_TYPES[config.type](config, client, settings)

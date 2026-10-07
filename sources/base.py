"""Source plugin interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from config.settings import Settings
from utils.http import HttpClient


class SourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    NO_DATA = "NO_DATA"
    BLOCKED = "BLOCKED"          # robots.txt disallows, or publisher returns 401/403
    DISABLED = "DISABLED"
    NEVER_RUN = "NEVER_RUN"


@dataclass
class RawItem:
    """Only what the dashboard needs: never full article bodies."""
    title: str
    url: str
    publisher: str
    summary: str | None = None
    published: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchOutcome:
    items: list[RawItem]
    not_modified: bool = False
    feed_errors: list[str] = field(default_factory=list)


@dataclass
class SourceConfig:
    name: str
    type: str
    publisher: str
    domain: str | None = None
    enabled: bool = True
    interval_minutes: int = 15
    feeds: list[str] = field(default_factory=list)
    notes: str | None = None
    is_original_publisher: bool = False
    tos_checked: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


class BaseSource(ABC):
    def __init__(self, config: SourceConfig, client: HttpClient, settings: Settings):
        self.config = config
        self.client = client
        self.settings = settings

    @abstractmethod
    def fetch(self) -> FetchOutcome:
        """Return raw items. Raise utils.http.FetchError subclasses on failure."""

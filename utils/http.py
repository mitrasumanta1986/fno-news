"""Shared HTTP client: honest User-Agent, robots.txt checks, per-domain throttling,
timeouts on every call, bounded retries and conditional GET."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import Settings
from utils.ratelimit import DomainRateLimiter
from utils.robots import RobotsCache

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 20 * 1024 * 1024


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimitedError(FetchError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message, 429)
        self.retry_after = retry_after


class BlockedError(FetchError):
    """HTTP 401/403: the publisher refuses this client. Never retried or circumvented."""


class RobotsDisallowedError(FetchError):
    pass


@dataclass
class FetchResponse:
    url: str
    status: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    not_modified: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(self, settings: Settings, rate_limiter: DomainRateLimiter | None = None):
        self.settings = settings
        self.rate_limiter = rate_limiter or DomainRateLimiter(settings.domain_min_interval)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent, "Accept-Encoding": "gzip, deflate"})
        if "@" in settings.contact_email:
            self.session.headers["From"] = settings.contact_email
        retry = Retry(
            total=3, connect=3, read=2, status=2, backoff_factor=1.5,
            status_forcelist=(500, 502, 503, 504), allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True, raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.robots = RobotsCache(self._fetch_robots)
        self._validators_path: Path = settings.cache_dir / "http_validators.json"
        self._validators_lock = threading.Lock()
        self._validators = self._load_validators()

    # -- robots -------------------------------------------------------------------------------
    def _fetch_robots(self, url: str) -> tuple[int, str]:
        self.rate_limiter.wait(urlsplit(url).netloc)
        resp = self.session.get(url, timeout=self._timeout)
        return resp.status_code, resp.text

    def is_allowed(self, url: str) -> bool:
        return self.robots.can_fetch(self.settings.robots_agent_token, url)

    # -- conditional GET validators ------------------------------------------------------------
    def _load_validators(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads(self._validators_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_validator(self, url: str, headers: dict[str, str]) -> None:
        entry = {k: headers[k] for k in ("ETag", "Last-Modified") if k in headers}
        if not entry:
            return
        with self._validators_lock:
            self._validators[url] = entry
            try:
                self._validators_path.parent.mkdir(parents=True, exist_ok=True)
                self._validators_path.write_text(json.dumps(self._validators), encoding="utf-8")
            except OSError as exc:
                log.debug("could not persist validators: %s", exc)

    @property
    def _timeout(self) -> tuple[float, float]:
        return (self.settings.connect_timeout, self.settings.read_timeout)

    # -- main entry ---------------------------------------------------------------------------
    def get(self, url: str, *, conditional: bool = False, check_robots: bool = True) -> FetchResponse:
        if urlsplit(url).scheme not in ("http", "https"):
            raise FetchError(f"unsupported URL scheme: {url}")
        if check_robots and not self.is_allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")

        headers: dict[str, str] = {}
        if conditional:
            cached = self._validators.get(url, {})
            if "ETag" in cached:
                headers["If-None-Match"] = cached["ETag"]
            if "Last-Modified" in cached:
                headers["If-Modified-Since"] = cached["Last-Modified"]

        self.rate_limiter.wait(urlsplit(url).netloc)
        try:
            resp = self.session.get(url, headers=headers, timeout=self._timeout, stream=True)
        except requests.RequestException as exc:
            raise FetchError(f"{type(exc).__name__}: {exc}") from exc

        with resp:
            if resp.status_code == 304:
                return FetchResponse(url, 304, headers=dict(resp.headers), not_modified=True)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
                raise RateLimitedError(f"HTTP 429 from {url}", retry_after=seconds)
            if resp.status_code in (401, 403):
                raise BlockedError(f"HTTP {resp.status_code} (access refused) for {url}", resp.status_code)
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}", resp.status_code)
            body = resp.raw.read(MAX_BODY_BYTES + 1, decode_content=True)
            if len(body) > MAX_BODY_BYTES:
                raise FetchError(f"response too large for {url}")
            result = FetchResponse(url, resp.status_code, body, dict(resp.headers))
        if conditional:
            self._save_validator(url, result.headers)
        return result

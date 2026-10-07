"""URL canonicalization and content hashing used for de-duplication."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "fbclid", "gclid", "ref", "from", "source", "cmpid", "icid", "src", "utm", "mc_cid", "mc_eid",
    "ocid", "ito", "_ga", "yclid",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """Lower-case scheme/host, drop fragments, tracking params and AMP suffixes."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    host = parts.netloc.lower()
    path = re.sub(r"/amp/?$", "", parts.path) or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS and k.lower() != "amp"
    ]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return sha256(canonicalize_url(url))


def normalize_headline(headline: str) -> str:
    text = headline.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_hash(headline: str) -> str:
    return sha256(normalize_headline(headline))

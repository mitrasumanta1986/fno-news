from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_yaml  # noqa: E402
from processing.entities import BrokerageMatcher, StockTagger, build_alias_map  # noqa: E402
from processing.normalizer import Normalizer  # noqa: E402
from processing.rec_extractor import RecommendationExtractor  # noqa: E402

# (id, symbol, NSE-style company name) — a realistic slice of the F&O universe
SAMPLE_STOCKS = [
    (1, "HDFCBANK", "HDFC Bank Ltd."), (2, "PETRONET", "Petronet LNG Ltd."), (3, "DRREDDY", "Dr. Reddy's Laboratories Ltd."),
    (4, "HINDZINC", "Hindustan Zinc Ltd."), (5, "INDIGO", "InterGlobe Aviation Ltd."), (6, "DIXON", "Dixon Technologies (India) Ltd."),
    (7, "M&M", "Mahindra & Mahindra Ltd."), (8, "LT", "Larsen & Toubro Ltd."), (9, "LTF", "L&T Finance Ltd."),
    (10, "TITAN", "Titan Company Ltd."), (11, "SBIN", "State Bank of India"), (12, "TATASTEEL", "Tata Steel Ltd."),
    (13, "KOTAKBANK", "Kotak Mahindra Bank Ltd."), (14, "ANGELONE", "Angel One Ltd."), (15, "INFY", "Infosys Ltd."),
    (16, "BEL", "Bharat Electronics Ltd."), (17, "MARUTI", "Maruti Suzuki India Ltd."), (18, "JSWSTEEL", "JSW Steel Ltd."),
    (19, "ITC", "ITC Ltd."), (20, "POLICYBZR", "PB Fintech Ltd."),
]


def _alias_rows():
    curated = {str(k): [str(a) for a in v] for k, v in load_yaml("aliases.yaml")["aliases"].items()}
    alias_map = build_alias_map([(i, s, n) for i, s, n in SAMPLE_STOCKS], curated)
    symbol_of = {i: s for i, s, _ in SAMPLE_STOCKS}
    return [(sid, symbol_of[sid], alias, kind) for sid, items in alias_map.items() for alias, kind in items]


@pytest.fixture(scope="session")
def tagger() -> StockTagger:
    return StockTagger(_alias_rows())


@pytest.fixture(scope="session")
def brokers() -> BrokerageMatcher:
    return BrokerageMatcher(load_yaml("brokerages.yaml")["brokerages"])


@pytest.fixture(scope="session")
def normalizer() -> Normalizer:
    return Normalizer(load_yaml("normalization.yaml"))


@pytest.fixture(scope="session")
def extractor(tagger, brokers, normalizer) -> RecommendationExtractor:
    return RecommendationExtractor(tagger, brokers, normalizer)


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Isolated migrated database with the sample stocks loaded."""
    from config import settings as settings_mod
    from database.connection import connect
    from database.migrate import migrate
    from database.repository import FoEntry, Repository
    from datetime import date

    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AI_ENABLED", "false")
    settings_mod.get_settings.cache_clear()
    conn = connect()
    migrate(conn)
    repo = Repository(conn)
    repo.apply_fo_universe([FoEntry(s, n, 100) for _, s, n in SAMPLE_STOCKS], date(2026, 9, 25))
    stocks = [(r["id"], r["symbol"], r["name"]) for r in repo.active_stocks()]
    curated = {str(k): [str(a) for a in v] for k, v in load_yaml("aliases.yaml")["aliases"].items()}
    repo.replace_aliases(build_alias_map(stocks, curated))
    yield repo
    conn.close()
    settings_mod.get_settings.cache_clear()

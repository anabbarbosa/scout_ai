import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scout_ai.db.models import Competitor, CompetitorTier, Recommendation, Source, priority_score
from scout_ai.db.seed import COMPETITORS
from scout_ai.db.setup import alembic_config, create_database, setup_database

# Set to a PostgreSQL URL (e.g. the CI service) to also run the setup against a real server.
POSTGRES_URL = os.environ.get("SCOUT_TEST_POSTGRES_URL")


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"


@pytest.fixture
def engine(sqlite_url: str) -> Iterator[Engine]:
    setup_database(sqlite_url)
    engine = create_engine(sqlite_url)
    yield engine
    engine.dispose()


def _counts(engine: Engine) -> tuple[int, int]:
    with Session(engine) as session:
        competitors = session.scalar(select(func.count()).select_from(Competitor))
        sources = session.scalar(select(func.count()).select_from(Source))
    assert competitors is not None and sources is not None
    return competitors, sources


def test_setup_creates_schema_and_seeds(engine: Engine) -> None:
    assert _counts(engine) == (len(COMPETITORS), sum(len(c.sources) for c in COMPETITORS))
    with Session(engine) as session:
        tiers = {c.name: c.tier for c in session.scalars(select(Competitor))}
    top3 = {name for name, tier in tiers.items() if tier is CompetitorTier.TOP3}
    assert top3 == {"LabWare", "STARLIMS", "Clinisys"}


def test_setup_is_idempotent(engine: Engine, sqlite_url: str) -> None:
    before = _counts(engine)
    setup_database(sqlite_url)
    assert _counts(engine) == before


def test_migrations_match_models(engine: Engine, sqlite_url: str) -> None:
    # Fails if a model changed without a new Alembic revision.
    command.check(alembic_config(sqlite_url))


def test_migrations_downgrade_cleanly(engine: Engine, sqlite_url: str) -> None:
    command.downgrade(alembic_config(sqlite_url), "base")
    with engine.connect() as conn:
        tables = conn.scalars(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    assert set(tables) == {"alembic_version"}


def test_create_database_skips_sqlite(sqlite_url: str) -> None:
    assert create_database(sqlite_url) is False


def test_recommendation_priority_is_computed(engine: Engine) -> None:
    rec = Recommendation(action="Test", impact=4, cost=2, effort=2, confidence=3)
    assert rec.priority == priority_score(impact=4, cost=2, effort=2, confidence=3) == 3.0
    with Session(engine) as session, session.begin():
        session.add(rec)
        session.flush()
        assert rec.evidence == []


def test_recommendation_scores_are_bounded(engine: Engine) -> None:
    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(Recommendation(action="Bad", impact=6, cost=1, effort=1, confidence=1))
        session.flush()


@pytest.mark.skipif(POSTGRES_URL is None, reason="SCOUT_TEST_POSTGRES_URL not set")
def test_setup_on_postgres() -> None:
    assert POSTGRES_URL is not None
    setup_database(POSTGRES_URL)
    setup_database(POSTGRES_URL)  # second run: database exists, nothing to migrate or insert
    engine = create_engine(POSTGRES_URL)
    try:
        assert _counts(engine) == (
            len(COMPETITORS),
            sum(len(c.sources) for c in COMPETITORS),
        )
        command.check(alembic_config(POSTGRES_URL))
    finally:
        engine.dispose()

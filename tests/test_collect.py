"""`scout collect` end to end on SQLite with a fake website (guide Step 3 "Done when")."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.orm import Session

from scout_ai.collectors import build_collectors
from scout_ai.collectors.run import Result, Status, collect_sources
from scout_ai.db.models import Competitor, CompetitorTier, Snapshot, Source, SourceType
from scout_ai.db.setup import setup_database
from tests.collector_site import FakeSite, fixture, polite_client

ROOT = "https://acme.test"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    engine = create_engine(url)
    with Session(engine) as session, session.begin():
        # Replace the seeded competitors so nothing points at real websites.
        session.execute(delete(Source))  # SQLite does not cascade bulk deletes
        session.execute(delete(Competitor))
        acme = Competitor(name="Acme", website=f"{ROOT}/", tier=CompetitorTier.TOP3)
        acme.sources = [
            Source(type=SourceType.HOMEPAGE, url=f"{ROOT}/"),
            Source(type=SourceType.BLOG, url=f"{ROOT}/blog"),
            Source(type=SourceType.PRESS, url=f"{ROOT}/news/"),
            Source(type=SourceType.REVIEWS, url="https://reviews.test/acme"),
            Source(type=SourceType.EVENTS, url=f"{ROOT}/old-events", active=False),
        ]
        session.add(acme)
    yield engine
    engine.dispose()


@pytest.fixture
def site() -> FakeSite:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "User-agent: *\nDisallow: /private/\n")
    site.serve(f"{ROOT}/", fixture("homepage.html"))
    site.serve(f"{ROOT}/blog", fixture("blog_with_feed.html"))
    site.serve(f"{ROOT}/blog/rss.xml", fixture("blog_rss.xml"))
    site.serve(f"{ROOT}/news/", fixture("press_articles.html"))
    return site


def _collect(engine: Engine, site: FakeSite) -> dict[str, Status]:
    with Session(engine) as session:
        results = collect_sources(session, build_collectors(polite_client(site, delay=0)))
    return {result.url: result.status for result in results}


def _snapshots(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Snapshot)) or 0


def test_second_run_without_changes_creates_no_snapshots(engine: Engine, site: FakeSite) -> None:
    first = _collect(engine, site)
    assert first == {
        f"{ROOT}/": Status.NEW,
        f"{ROOT}/blog": Status.NEW,
        f"{ROOT}/news/": Status.NEW,
        "https://reviews.test/acme": Status.UNSUPPORTED,
    }
    assert _snapshots(engine) == 3

    second = _collect(engine, site)
    assert set(second.values()) == {Status.UNCHANGED, Status.UNSUPPORTED}
    assert _snapshots(engine) == 3


def test_a_changed_page_creates_one_snapshot(engine: Engine, site: FakeSite) -> None:
    _collect(engine, site)
    homepage = fixture("homepage.html").replace(b"Environmental", b"Clinical")
    site.serve(f"{ROOT}/", homepage)
    # A markup-only change elsewhere is not a change.
    site.serve(f"{ROOT}/news/", fixture("press_articles.html").replace(b"a.png", b"b.png"))

    results = _collect(engine, site)
    assert results[f"{ROOT}/"] == Status.NEW
    assert results[f"{ROOT}/news/"] == Status.UNCHANGED
    with Session(engine) as session:
        texts = session.scalars(
            select(Snapshot.raw_text)
            .join(Source)
            .where(Source.url == f"{ROOT}/")
            .order_by(Snapshot.id)
        ).all()
    assert len(texts) == 2
    assert "Clinical" in texts[1] and "Clinical" not in texts[0]


def test_failures_are_reported_and_the_run_continues(engine: Engine, site: FakeSite) -> None:
    site.serve(f"{ROOT}/", "busy", status=503)
    site.serve(f"{ROOT}/robots.txt", "User-agent: *\nDisallow: /blog\n")

    with Session(engine) as session:
        results = collect_sources(session, build_collectors(polite_client(site, delay=0)))
    by_url = {result.url: result for result in results}
    assert by_url[f"{ROOT}/"] == Result(
        "Acme", SourceType.HOMEPAGE, f"{ROOT}/", Status.FAILED, "HTTP 503"
    )
    assert by_url[f"{ROOT}/blog"].status == Status.BLOCKED
    assert by_url[f"{ROOT}/news/"].status == Status.NEW
    assert _snapshots(engine) == 1

"""Collect every active source and store a snapshot only when its text changed (guide Step 3.3)."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from scout_ai.collectors.base import BlockedError, Collector, CollectorError
from scout_ai.db.models import Snapshot, Source, SourceType


class Status(StrEnum):
    NEW = "new"  # first snapshot, or the text changed
    UNCHANGED = "unchanged"
    BLOCKED = "blocked"  # robots.txt, 401 or 403: the site does not want us there
    UNSUPPORTED = "unsupported"  # no collector for this source type yet
    FAILED = "failed"  # network error, HTTP error or empty page: worth a look


@dataclass(frozen=True)
class Result:
    competitor: str
    source_type: SourceType
    url: str
    status: Status
    detail: str = ""


def collect_sources(session: Session, collectors: dict[SourceType, Collector]) -> list[Result]:
    """Collect each active source, committing after each one so a later failure loses nothing."""
    sources = session.scalars(
        select(Source)
        .where(Source.active)
        .options(joinedload(Source.competitor))
        .order_by(Source.competitor_id, Source.id)
    ).all()
    results = []
    for source in sources:
        results.append(collect_source(session, source, collectors))
        session.commit()
    return results


def collect_source(
    session: Session, source: Source, collectors: dict[SourceType, Collector]
) -> Result:
    def result(status: Status, detail: str = "") -> Result:
        return Result(source.competitor.name, source.type, source.url, status, detail)

    collector = collectors.get(source.type)
    if collector is None:
        return result(Status.UNSUPPORTED, f"no collector for {source.type} sources yet")
    try:
        snapshot = collector.fetch(source)
    except BlockedError as error:
        return result(Status.BLOCKED, str(error))
    except CollectorError as error:
        return result(Status.FAILED, str(error))

    latest = session.scalar(
        select(Snapshot.content_hash)
        .where(Snapshot.source_id == source.id)
        .order_by(Snapshot.fetched_at.desc(), Snapshot.id.desc())
        .limit(1)
    )
    if latest == snapshot.content_hash:
        return result(Status.UNCHANGED)
    session.add(snapshot)
    return result(Status.NEW)

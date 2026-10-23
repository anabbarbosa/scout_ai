"""Seed the monitored competitors and their sources (README §3). Safe to run repeatedly."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout_ai.db.models import Competitor, CompetitorTier, Frequency, Source, SourceType


@dataclass(frozen=True)
class SeedCompetitor:
    name: str
    website: str
    tier: CompetitorTier
    sources: list[tuple[SourceType, str, Frequency]] = field(default_factory=list)


W, M = Frequency.WEEKLY, Frequency.MONTHLY

# URLs checked on 2026-10-23. labvantage.com answers 403 to non-browser clients, so only
# its homepage is listed until a collector confirms which pages it may fetch.
COMPETITORS = [
    SeedCompetitor(
        "LabVantage",
        "https://www.labvantage.com/",
        CompetitorTier.TOP3,
        [(SourceType.HOMEPAGE, "https://www.labvantage.com/", W)],
    ),
    SeedCompetitor(
        "LabWare",
        "https://www.labware.com/",
        CompetitorTier.TOP3,
        [
            (SourceType.HOMEPAGE, "https://www.labware.com/", W),
            (SourceType.BLOG, "https://www.labware.com/blog", W),
            (SourceType.EVENTS, "https://www.labware.com/events", W),
        ],
    ),
    SeedCompetitor(
        "Clinisys",
        "https://www.clinisys.com/",
        CompetitorTier.TOP3,
        [(SourceType.HOMEPAGE, "https://www.clinisys.com/int/en", W)],
    ),
    SeedCompetitor(
        "STARLIMS",
        "https://www.starlims.com/",
        CompetitorTier.WATCHLIST,
        [
            (SourceType.HOMEPAGE, "https://www.starlims.com/", M),
            (SourceType.PRESS, "https://www.starlims.com/resources/?taxonomy=category%3Anews", M),
        ],
    ),
    SeedCompetitor(
        "CloudLIMS",
        "https://cloudlims.com/",
        CompetitorTier.WATCHLIST,
        [
            (SourceType.HOMEPAGE, "https://cloudlims.com/", M),
            (SourceType.BLOG, "https://cloudlims.com/blog/", M),
            (SourceType.PRESS, "https://cloudlims.com/news/", M),
            (SourceType.PRICING, "https://cloudlims.com/lims-software-pricing/", M),
        ],
    ),
]


def seed(session: Session) -> None:
    """Insert missing competitors and sources; existing rows are updated in place."""
    for item in COMPETITORS:
        competitor = session.scalar(select(Competitor).where(Competitor.name == item.name))
        if competitor is None:
            competitor = Competitor(name=item.name)
            session.add(competitor)
        competitor.website = item.website
        competitor.tier = item.tier

        existing = {source.url: source for source in competitor.sources}
        for source_type, url, frequency in item.sources:
            source = existing.get(url)
            if source is None:
                source = Source(url=url)
                competitor.sources.append(source)
            source.type = source_type
            source.frequency = frequency
    session.flush()

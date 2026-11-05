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
CLINISYS = "https://www.clinisys.com/int/en"

# URLs checked on 2026-10-23; jobs, segment, events and news pages on 2026-11-05. Top 3
# sources are collected weekly, watchlist ones monthly. Segment pages cover the myLIMS
# segments: food, environmental/water, agribusiness, chemical/industrial and pharma.
# STARLIMS jobs are on ADP Workforce Now (JavaScript only): not listed.
# Top 3 changed on 2026-11-05 (README §3): STARLIMS replaced Clinisys because it shows up in
# HubSpot deals, then Clinisys replaced LabVantage because LabVantage cannot be collected:
# labvantage.com and Business Wire answer 403 to bots (robots.txt included) and Google
# News disallows its RSS. LabVantage's homepage stays listed, so `scout collect` reports
# `blocked` until the site lets bots in.
COMPETITORS = [
    SeedCompetitor(
        "LabVantage",
        "https://www.labvantage.com/",
        CompetitorTier.WATCHLIST,
        [(SourceType.HOMEPAGE, "https://www.labvantage.com/", M)],
    ),
    SeedCompetitor(
        "LabWare",
        "https://www.labware.com/",
        CompetitorTier.TOP3,
        [
            (SourceType.HOMEPAGE, "https://www.labware.com/", W),
            (SourceType.BLOG, "https://www.labware.com/blog", W),
            (SourceType.EVENTS, "https://www.labware.com/events", W),
            (SourceType.EVENTS, "https://www.labware.com/events/tradeshows", W),
            (SourceType.EVENTS, "https://www.labware.com/events/webinars-seminars", W),
            # News posts are also in the blog feed, but this keeps them typed as press.
            (SourceType.PRESS, "https://www.labware.com/blog/tag/news", W),
            (SourceType.JOBS, "https://www.labware.com/about/careers", W),
            *(
                (SourceType.SEGMENT_PAGE, f"https://www.labware.com/industries/{slug}", W)
                for slug in (
                    "food-beverage",
                    "water-environmental",
                    "pharmaceutical",
                    "process-chemical",
                )
            ),
        ],
    ),
    SeedCompetitor(
        "Clinisys",
        "https://www.clinisys.com/",
        CompetitorTier.TOP3,
        [
            (SourceType.HOMEPAGE, "https://www.clinisys.com/int/en", W),
            # Teamtailor job board feed: title, department and countries of each opening
            (SourceType.JOBS, "https://careers.clinisys.com/jobs.rss", W),
            (SourceType.PRESS, f"{CLINISYS}/news-events/category/news/", W),
            (SourceType.BLOG, f"{CLINISYS}/news-events/category/insight/", W),
            (SourceType.EVENTS, f"{CLINISYS}/news-events/category/events/", W),
            *(
                (SourceType.SEGMENT_PAGE, f"{CLINISYS}/clinisys-laboratory-solution/{slug}/", W)
                for slug in (
                    "clinisys-food-beverage-laboratory",
                    "clinisys-environmental-laboratory",
                    "clinisys-water-quality-laboratory",
                    "clinisys-crop-sciences-laboratory",
                    "clinisys-contract-services-laboratory",
                )
            ),
        ],
    ),
    SeedCompetitor(
        "STARLIMS",
        "https://www.starlims.com/",
        CompetitorTier.TOP3,
        [
            (SourceType.HOMEPAGE, "https://www.starlims.com/", W),
            # The resource library filters by category in the browser: the server returns
            # every category (news, blogs, product updates) at this URL. There is no events
            # page (/events/ redirects to the homepage) and robots.txt disallows /feed/.
            (SourceType.PRESS, "https://www.starlims.com/resources/?taxonomy=category%3Anews", W),
            (SourceType.PRICING, "https://www.starlims.com/pricing/", W),
            *(
                (SourceType.SEGMENT_PAGE, f"https://www.starlims.com/{slug}/", W)
                for slug in (
                    "food-and-beverage",
                    "environmental-sciences",
                    "agrochemical",
                    "chemical",
                    "life-sciences",
                )
            ),
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
            (SourceType.JOBS, "https://cloudlims.com/careers/openings/", M),
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

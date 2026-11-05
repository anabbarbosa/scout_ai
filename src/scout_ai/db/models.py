"""ORM models for the tables described in guide Step 2."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scout_ai.db.base import Base


class CompetitorTier(StrEnum):
    TOP3 = "top3"
    WATCHLIST = "watchlist"


class SourceType(StrEnum):
    HOMEPAGE = "homepage"
    SEGMENT_PAGE = "segment_page"
    COMPARISON = "comparison"
    BLOG = "blog"
    EVENTS = "events"
    PRESS = "press"
    JOBS = "jobs"
    REVIEWS = "reviews"
    PRICING = "pricing"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SignalType(StrEnum):
    MESSAGING_CHANGE = "messaging_change"
    COMPARISON_PAGE = "comparison_page"
    EVENT = "event"
    CONTENT = "content"
    PRESS_RELEASE = "press_release"
    JOB_POSTING = "job_posting"
    REVIEW = "review"
    PRICING = "pricing"
    OTHER = "other"


class DealOutcome(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Region(StrEnum):
    """Sales regions, as used by HubSpot and the Marketing spend exports."""

    NORTH_AMERICA = "north_america"
    BRAZIL = "brazil"
    LATAM = "latam"
    EMEA = "emea"
    APAC = "apac"
    OTHER = "other"

    @classmethod
    def from_label(cls, raw: str) -> Region:
        """Map HubSpot's and the spend report's spellings ("NA", "North America", "BRAZIL")."""
        return _REGION_LABELS.get(raw.strip().lower(), cls.OTHER)


_REGION_LABELS = {
    "north america": Region.NORTH_AMERICA,
    "na": Region.NORTH_AMERICA,
    "brazil": Region.BRAZIL,
    "latam": Region.LATAM,
    "emea": Region.EMEA,
    "apac": Region.APAC,
}


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    DONE = "done"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    """Store enum values as VARCHAR + CHECK, so adding a value is a simple migration."""
    return SAEnum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


def _timestamp(*, onupdate: bool = False) -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now() if onupdate else None,
    )


JSONType = JSON().with_variant(JSONB(), "postgresql")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    website: Mapped[str] = mapped_column(String(500))
    tier: Mapped[CompetitorTier] = mapped_column(_enum(CompetitorTier))
    created_at: Mapped[datetime] = _timestamp()

    sources: Mapped[list[Source]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )
    signals: Mapped[list[Signal]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )
    deals: Mapped[list[DealCompetition]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("competitor_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[SourceType] = mapped_column(_enum(SourceType))
    url: Mapped[str] = mapped_column(String(1000))
    frequency: Mapped[Frequency] = mapped_column(_enum(Frequency), default=Frequency.WEEKLY)
    active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = _timestamp()

    competitor: Mapped[Competitor] = relationship(back_populates="sources")
    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"
    # Change detection reads the latest snapshot of a source.
    __table_args__ = (Index("ix_snapshots_source_id_fetched_at", "source_id", "fetched_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    fetched_at: Mapped[datetime] = _timestamp()
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 hex of the cleaned text
    raw_text: Mapped[str] = mapped_column(Text)
    # Set by `scout analyze` (guide Step 4), also when the change had no signal, so each
    # snapshot is sent to the LLM once. NULL means not analyzed yet.
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_prompt_version: Mapped[str | None] = mapped_column(String(50))

    source: Mapped[Source] = relationship(back_populates="snapshots")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[SignalType] = mapped_column(_enum(SignalType))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    relevance: Mapped[str | None] = mapped_column(Text)  # relevance to myLIMS segments
    url: Mapped[str] = mapped_column(String(1000))
    prompt_version: Mapped[str | None] = mapped_column(String(50))  # guide Step 4.4
    detected_at: Mapped[datetime] = _timestamp()

    competitor: Mapped[Competitor] = relationship(back_populates="signals")
    snapshot: Mapped[Snapshot | None] = relationship()


class FunnelMetric(Base):
    """Aggregated internal funnel data; no personal contact data is stored here."""

    __tablename__ = "funnel_metrics"
    # One row per period/region/channel/campaign keeps `scout load` idempotent.
    __table_args__ = (UniqueConstraint("period", "region", "channel", "campaign"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[date] = mapped_column(Date)  # first day of the month
    region: Mapped[Region] = mapped_column(_enum(Region))  # joins with marketing_spend
    channel: Mapped[str] = mapped_column(String(100))
    campaign: Mapped[str] = mapped_column(String(200), default="", server_default="")
    leads: Mapped[int] = mapped_column(default=0, server_default="0")
    mqls: Mapped[int] = mapped_column(default=0, server_default="0")
    sqls: Mapped[int] = mapped_column(default=0, server_default="0")
    opportunities: Mapped[int] = mapped_column(default=0, server_default="0")
    deals_won: Mapped[int] = mapped_column(default=0, server_default="0")
    revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0), server_default="0")
    synced_at: Mapped[datetime] = _timestamp(onupdate=True)


class DealCompetition(Base):
    __tablename__ = "deals_competition"
    __table_args__ = (UniqueConstraint("deal_id", "competitor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(50), index=True)  # HubSpot deal ID
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    outcome: Mapped[DealOutcome] = mapped_column(_enum(DealOutcome))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    closed_at: Mapped[date | None] = mapped_column(Date)

    competitor: Mapped[Competitor] = relationship(back_populates="deals")


class Campaign(Base):
    """A marketing campaign seen in HubSpot: the closest thing to an "initiative" (Step 7)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)  # same value as funnel_metrics
    channel: Mapped[str] = mapped_column(String(100))
    first_mql_at: Mapped[date | None] = mapped_column(Date)  # period the campaign was active
    last_mql_at: Mapped[date | None] = mapped_column(Date)


class MarketingSpend(Base):
    """Monthly Marketing spend per region, from the Marketing cost exports (Step 5)."""

    __tablename__ = "marketing_spend"
    __table_args__ = (UniqueConstraint("period", "region"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[date] = mapped_column(Date)  # first day of the month
    region: Mapped[Region] = mapped_column(_enum(Region))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class WeeklySummary(Base):
    """One weekly summary (guide Step 6), shown on the dashboard's notifications page."""

    __tablename__ = "weekly_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One per day: running `scout report` again the same day replaces it.
    report_date: Mapped[date] = mapped_column(Date, unique=True)
    title: Mapped[str] = mapped_column(String(200))
    month: Mapped[date | None] = mapped_column(Date)  # month of the funnel and spend tables
    signal_count: Mapped[int] = mapped_column(default=0, server_default="0")
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp(onupdate=True)


def priority_score(*, impact: int, cost: int, effort: int, confidence: int) -> float:
    """README §5: impact * confidence / (cost + effort). Computed in code, never by the LLM."""
    return round(impact * confidence / (cost + effort), 3)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = tuple(
        CheckConstraint(f"{axis} BETWEEN 1 AND 5", name=f"{axis}_range")
        for axis in ("impact", "cost", "effort", "confidence")
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(Text)
    # [{"kind": "signal" | "funnel_metric" | "deal", "id": ..., "url": ..., "note": ...}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    impact: Mapped[int] = mapped_column(SmallInteger)
    cost: Mapped[int] = mapped_column(SmallInteger)
    effort: Mapped[int] = mapped_column(SmallInteger)
    confidence: Mapped[int] = mapped_column(SmallInteger)
    priority: Mapped[float] = mapped_column(index=True)
    status: Mapped[RecommendationStatus] = mapped_column(
        _enum(RecommendationStatus), default=RecommendationStatus.PROPOSED, index=True
    )
    clickup_task_id: Mapped[str | None] = mapped_column(String(50))
    outcome: Mapped[str | None] = mapped_column(Text)  # measured effect after execution (Step 8)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp(onupdate=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.priority is None:
            self.priority = priority_score(
                impact=self.impact, cost=self.cost, effort=self.effort, confidence=self.confidence
            )

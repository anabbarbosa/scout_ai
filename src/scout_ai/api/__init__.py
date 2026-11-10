"""The web dashboard's API (guide Step 10), and the front end it serves.

Every endpoint reads the existing tables; the only write is `PATCH /api/recommendations/{id}`,
which approves or rejects a recommendation through `scout_ai.review` (Step 8, dry run).
The front end in `scout_ai/web/` is a static single-page app served from `/`.

There is no login: `scout serve` listens on localhost only, and the team drives the
dashboard during the demo.
"""

from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from scout_ai import __version__
from scout_ai.db.models import (
    Campaign,
    Competitor,
    DealCompetition,
    DealOutcome,
    FunnelMetric,
    MarketingSpend,
    Recommendation,
    RecommendationStatus,
    Region,
    Signal,
    SignalType,
    WeeklySummary,
)
from scout_ai.reports.weekly import DEMO_LABEL, REGION_LABELS, FunnelCounts
from scout_ai.review import RecommendationNotFoundError, ReviewError, approve, reject

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEMO_BANNER = "Synthetic demo data, generated from real patterns"

Row = dict[str, Any]


class ReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]


def create_app(engine: Engine | None = None) -> FastAPI:
    """The API under /api and the front end under /; `engine` defaults to DATABASE_URL."""
    if engine is None:
        from scout_ai.db.session import get_engine

        engine = get_engine()
    app = FastAPI(title="Scout AI", version=__version__, docs_url="/api/docs", openapi_url=None)
    app.state.engine = engine
    app.include_router(_router())

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


DB = Annotated[Session, Depends(_session)]


def _router() -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.get("/meta")
    def meta(db: DB) -> Row:
        months = sorted(
            {*db.scalars(select(FunnelMetric.period)), *db.scalars(select(MarketingSpend.period))}
        )
        channels = sorted(set(db.scalars(select(FunnelMetric.channel))))
        return {
            "banner": DEMO_BANNER,
            "demo_label": DEMO_LABEL,
            "regions": [{"value": r.value, "label": label} for r, label in REGION_LABELS.items()],
            "channels": channels,
            "months": [m.isoformat() for m in months],
            "latest_spend_month": _iso(db.scalar(select(func.max(MarketingSpend.period)))),
            "signal_types": [t.value for t in SignalType],
        }

    @api.get("/competitors")
    def competitors(db: DB) -> list[Row]:
        week_ago = datetime.now(UTC) - timedelta(days=7)
        recent = dict(
            db.execute(
                select(Signal.competitor_id, func.count())
                .where(Signal.detected_at >= week_ago)
                .group_by(Signal.competitor_id)
            ).all()
        )
        return [
            {
                "id": c.id,
                "name": c.name,
                "website": c.website,
                "tier": c.tier.value,
                "signals_last_7_days": recent.get(c.id, 0),
            }
            for c in db.scalars(select(Competitor).order_by(Competitor.tier, Competitor.name))
        ]

    @api.get("/signals")
    def signals(
        db: DB,
        competitor: str | None = None,
        signal_type: Annotated[SignalType | None, Query(alias="type")] = None,
        since: date | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[Row]:
        query = select(Signal, Competitor).join(Competitor)
        if competitor:
            query = query.where(Competitor.name == competitor)
        if signal_type:
            query = query.where(Signal.type == signal_type)
        if since:
            query = query.where(Signal.detected_at >= datetime.combine(since, time(), UTC))
        query = query.order_by(Signal.detected_at.desc(), Signal.id.desc()).limit(limit)
        return [
            {
                "id": s.id,
                "competitor": c.name,
                "tier": c.tier.value,
                "type": s.type.value,
                "title": s.title,
                "summary": s.summary,
                "relevance": s.relevance,
                "url": s.url,
                "detected_at": s.detected_at.isoformat(),
            }
            for s, c in db.execute(query)
        ]

    @api.get("/funnel")
    def funnel(
        db: DB,
        by: Literal["region", "channel", "campaign", "total"] = "region",
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        region: Region | None = None,
        channel: str | None = None,
        campaign: str | None = None,
    ) -> list[Row]:
        """Monthly funnel per group: one row per month and region, channel or campaign."""
        query = select(FunnelMetric)
        if start:
            query = query.where(FunnelMetric.period >= start)
        if end:
            query = query.where(FunnelMetric.period <= end)
        if region:
            query = query.where(FunnelMetric.region == region)
        if channel is not None:
            query = query.where(FunnelMetric.channel == channel)
        if campaign is not None:
            query = query.where(FunnelMetric.campaign == campaign)
        totals: dict[tuple[date, str], Row] = {}
        for row in db.scalars(query):
            key = "Total" if by == "total" else _group_label(by, row)
            item = totals.setdefault(
                (row.period, key),
                {
                    "period": row.period.isoformat(),
                    "group": key,
                    "leads": 0,
                    "mqls": 0,
                    "sqls": 0,
                    "opportunities": 0,
                    "deals_won": 0,
                    "revenue": 0.0,
                },
            )
            for field in ("leads", "mqls", "sqls", "opportunities", "deals_won"):
                item[field] += getattr(row, field)
            item["revenue"] += float(row.revenue)
        return [totals[key] for key in sorted(totals)]

    @api.get("/spend")
    def spend(
        db: DB,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        region: Region | None = None,
    ) -> list[Row]:
        """Monthly spend per region with its cost metrics (spend is only known per region)."""
        counts: dict[tuple[date, Region], FunnelCounts] = defaultdict(FunnelCounts)
        spend_query = select(MarketingSpend)
        funnel_query = select(FunnelMetric)
        if start:
            spend_query = spend_query.where(MarketingSpend.period >= start)
            funnel_query = funnel_query.where(FunnelMetric.period >= start)
        if end:
            spend_query = spend_query.where(MarketingSpend.period <= end)
            funnel_query = funnel_query.where(FunnelMetric.period <= end)
        if region:
            spend_query = spend_query.where(MarketingSpend.region == region)
            funnel_query = funnel_query.where(FunnelMetric.region == region)
        for s in db.scalars(spend_query):
            counts[(s.period, s.region)].spend = s.amount
        for f in db.scalars(funnel_query):
            key = (f.period, f.region)
            if key in counts:  # cost metrics only where spend is known
                counts[key].mqls += f.mqls
                counts[key].opportunities += f.opportunities
                counts[key].deals_won += f.deals_won
        return [
            {
                "period": period.isoformat(),
                "region": r.value,
                "region_label": REGION_LABELS[r],
                "spend": _float(c.spend),
                "mqls": c.mqls,
                "opportunities": c.opportunities,
                "deals_won": c.deals_won,
                "cost_per_mql": _float(c.cost_per_mql),
                "opportunities_per_1k": _float(c.opportunities_per_1k),
                "cac": _float(c.cac),
            }
            for (period, r), c in sorted(counts.items(), key=lambda item: item[0])
        ]

    @api.get("/campaigns")
    def campaigns(db: DB) -> list[Row]:
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for name, mqls, opportunities, won in db.execute(
            select(
                FunnelMetric.campaign,
                func.sum(FunnelMetric.mqls),
                func.sum(FunnelMetric.opportunities),
                func.sum(FunnelMetric.deals_won),
            ).group_by(FunnelMetric.campaign)
        ):
            totals[name] = [int(mqls or 0), int(opportunities or 0), int(won or 0)]
        rows = [
            {
                "id": c.id,
                "name": c.name,
                "channel": c.channel,
                "first_mql_at": _iso(c.first_mql_at),
                "last_mql_at": _iso(c.last_mql_at),
                "mqls": totals[c.name][0],
                "opportunities": totals[c.name][1],
                "deals_won": totals[c.name][2],
            }
            for c in db.scalars(select(Campaign))
        ]
        return sorted(rows, key=lambda row: (-row["mqls"], row["name"]))

    @api.get("/deals/competition")
    def deals_competition(db: DB, year: int | None = None) -> Row:
        """Won and lost per competitor in a year (by close date), and deals open now."""
        latest = db.scalar(select(func.max(DealCompetition.closed_at)))
        year = year or (latest.year if latest else date.today().year)
        stats: dict[int, Row] = {}
        for competitor in db.scalars(select(Competitor).order_by(Competitor.tier, Competitor.name)):
            stats[competitor.id] = {
                "competitor": competitor.name,
                "tier": competitor.tier.value,
                "won": 0,
                "lost": 0,
                "open": 0,
                "amount_won": 0.0,
                "amount_lost": 0.0,
            }
        for deal in db.scalars(select(DealCompetition)):
            item = stats[deal.competitor_id]
            amount = float(deal.amount or 0)
            if deal.outcome is DealOutcome.OPEN:
                item["open"] += 1
            elif deal.closed_at is not None and deal.closed_at.year == year:
                outcome = deal.outcome.value
                item[outcome] += 1
                item[f"amount_{outcome}"] += amount
        rows = [row for row in stats.values() if row["won"] or row["lost"] or row["open"]]
        for row in rows:
            closed = row["won"] + row["lost"]
            row["win_rate"] = row["won"] / closed if closed else None
        years = sorted(
            {d.year for d in db.scalars(select(DealCompetition.closed_at)) if d is not None}
        )
        return {"year": year, "years": years, "competitors": rows}

    @api.get("/recommendations")
    def recommendations(db: DB, status: RecommendationStatus | None = None) -> list[Row]:
        query = select(Recommendation)
        if status:
            query = query.where(Recommendation.status == status)
        query = query.order_by(
            Recommendation.created_at.desc(), Recommendation.priority.desc(), Recommendation.id
        )
        return [_recommendation(rec) for rec in db.scalars(query)]

    @api.patch("/recommendations/{recommendation_id}")
    def review(recommendation_id: int, body: ReviewRequest, db: DB) -> Row:
        """Approve or reject a proposed recommendation; approval returns the dry-run actions."""
        action = approve if body.status == "approved" else reject
        try:
            result = action(db, recommendation_id)
        except RecommendationNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except ReviewError as error:
            raise HTTPException(409, str(error)) from error
        db.commit()
        return {
            "recommendation": _recommendation(result.recommendation),
            "dry_run": result.dry_run,
            "clickup_task": result.task.body() if result.task else None,
            "hubspot_tags": [{"campaign": t.campaign, "tag": t.tag} for t in result.tags],
        }

    @api.get("/notifications")
    def notifications(db: DB) -> list[Row]:
        query = select(WeeklySummary).order_by(WeeklySummary.report_date.desc())
        return [_summary(s) for s in db.scalars(query)]

    @api.get("/notifications/{summary_id}")
    def notification(summary_id: int, db: DB) -> Row:
        summary = db.get(WeeklySummary, summary_id)
        if summary is None:
            raise HTTPException(404, f"summary {summary_id} not found")
        return {**_summary(summary), "markdown": summary.markdown}

    return api


def _group_label(by: str, row: FunnelMetric) -> str:
    if by == "region":
        return REGION_LABELS[row.region]
    if by == "channel":
        return row.channel or "(no channel)"
    return row.campaign or "(no campaign)"


def _recommendation(rec: Recommendation) -> Row:
    return {
        "id": rec.id,
        "action": rec.action,
        "status": rec.status.value,
        "priority": rec.priority,
        "impact": rec.impact,
        "cost": rec.cost,
        "effort": rec.effort,
        "confidence": rec.confidence,
        "evidence": rec.evidence,
        "clickup_task_id": rec.clickup_task_id,
        "created_at": rec.created_at.isoformat(),
    }


def _summary(summary: WeeklySummary) -> Row:
    return {
        "id": summary.id,
        "report_date": summary.report_date.isoformat(),
        "title": summary.title,
        "month": _iso(summary.month),
        "signal_count": summary.signal_count,
        "created_at": summary.created_at.isoformat(),
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None

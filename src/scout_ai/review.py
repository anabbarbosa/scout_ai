"""Approving or rejecting a recommendation and closing the loop: `scout approve` (Step 8).

Approving a proposed recommendation builds the ClickUp task for it (action, evidence,
scores and priority) and the tag for each HubSpot campaign its evidence cites, so results
can be traced back to it. The dashboard's approve button (Step 10) calls the same code.

For the hackathon both run as a dry run: they are returned and printed, never sent. The
recommendations are built on the synthetic demo dataset, so a real ClickUp task would
be work nobody should do, and its campaign names do not exist in HubSpot. Without a
real task, `clickup_task_id` stays empty. Measuring the effect of an executed
recommendation (items 3 and 4) needs real executions and comes after the hackathon.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout_ai.db.models import Campaign, Recommendation, RecommendationStatus

CLICKUP_TAG = "scout-ai"
DEMO_NOTE = (
    "Built on synthetic demo data generated from real patterns: it shows that the "
    "system works, not what the business should do."
)


class ReviewError(Exception):
    """The recommendation cannot be reviewed: it was already approved or rejected."""


class RecommendationNotFoundError(ReviewError):
    """No recommendation has this ID."""


@dataclass(frozen=True)
class ClickUpTask:
    """The body of `POST /api/v2/list/{list_id}/task` for an approved recommendation."""

    name: str
    markdown_description: str
    tags: list[str]

    def body(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "markdown_description": self.markdown_description,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class HubSpotTag:
    """A tag on a HubSpot campaign, linking its results to a recommendation."""

    campaign: str
    tag: str


@dataclass(frozen=True)
class Review:
    recommendation: Recommendation
    task: ClickUpTask | None = None  # only on approval
    tags: list[HubSpotTag] = field(default_factory=list)
    dry_run: bool = True


def recommendation_tag(recommendation: Recommendation) -> str:
    return f"scout-ai-rec-{recommendation.id}"


def build_task(recommendation: Recommendation) -> ClickUpTask:
    rec = recommendation
    lines = [
        f"**Recommended by Scout AI** (#{rec.id}, priority {rec.priority:.2f})",
        "",
        f"Impact {rec.impact}/5 · Confidence {rec.confidence}/5 · "
        f"Cost {rec.cost}/5 · Effort {rec.effort}/5",
        "",
        "## Evidence",
        "",
    ]
    for item in rec.evidence:
        label = f"[{item['label']}]({item['url']})" if item.get("url") else item["label"]
        lines.append(f"- **{label}**: {item['note']}")
        lines.append(f"  - {item['fact']}")
    lines += ["", f"_{DEMO_NOTE}_"]
    return ClickUpTask(
        name=rec.action,
        markdown_description="\n".join(lines),
        tags=[CLICKUP_TAG, recommendation_tag(rec)],
    )


def campaign_tags(session: Session, recommendation: Recommendation) -> list[HubSpotTag]:
    """One tag per stored campaign the evidence cites, in name order."""
    ids = {
        campaign_id
        for item in recommendation.evidence
        for campaign_id in item.get("records", {}).get("campaigns", [])
    }
    if not ids:
        return []
    names = session.scalars(
        select(Campaign.name).where(Campaign.id.in_(ids)).order_by(Campaign.name)
    )
    tag = recommendation_tag(recommendation)
    return [HubSpotTag(name, tag) for name in names]


def _proposed(session: Session, recommendation_id: int) -> Recommendation:
    rec = session.get(Recommendation, recommendation_id)
    if rec is None:
        raise RecommendationNotFoundError(f"recommendation {recommendation_id} not found")
    if rec.status is not RecommendationStatus.PROPOSED:
        raise ReviewError(f"recommendation {recommendation_id} is already {rec.status}")
    return rec


def approve(session: Session, recommendation_id: int) -> Review:
    """Approve a proposed recommendation and build its task and tags; the caller commits."""
    rec = _proposed(session, recommendation_id)
    rec.status = RecommendationStatus.APPROVED
    session.flush()
    return Review(rec, build_task(rec), campaign_tags(session, rec))


def reject(session: Session, recommendation_id: int) -> Review:
    """Reject a proposed recommendation; the caller commits."""
    rec = _proposed(session, recommendation_id)
    rec.status = RecommendationStatus.REJECTED
    session.flush()
    return Review(rec)

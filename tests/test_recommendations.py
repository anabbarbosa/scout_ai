"""Recommendations (guide Step 7) on SQLite, with a fake generator instead of the LLM."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.orm import Session

from scout_ai.analysis.recommendations import (
    MAX_RECOMMENDATIONS,
    PROMPT_VERSION,
    EvidenceRef,
    Proposal,
    ProposedRecommendation,
    RunResult,
    build_context,
    generate_recommendations,
)
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
)
from scout_ai.db.setup import setup_database
from scout_ai.reports.weekly import build_weekly_report, render_markdown

AUG, SEP = date(2026, 8, 1), date(2026, 9, 1)
TODAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 9, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)  # seeds the real competitor list
    engine = create_engine(url)
    yield engine
    engine.dispose()


def _id(session: Session, name: str) -> int:
    competitor_id = session.scalar(select(Competitor.id).where(Competitor.name == name))
    assert competitor_id is not None
    return competitor_id


def _fill(engine: Engine) -> int:
    """Insert a small dataset; return the ID of the recent signal."""
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                FunnelMetric(
                    period=SEP,
                    region=Region.BRAZIL,
                    channel="Paid Search",
                    campaign="Food Labs Webinar",
                    mqls=60,
                    opportunities=6,
                    deals_won=1,
                ),
                FunnelMetric(
                    period=AUG,
                    region=Region.BRAZIL,
                    channel="Paid Search",
                    campaign="Food Labs Webinar",
                    mqls=50,
                    opportunities=10,
                    deals_won=2,
                ),
                FunnelMetric(period=SEP, region=Region.EMEA, channel="Referrals", mqls=10),
                Campaign(
                    name="Food Labs Webinar",
                    channel="Paid Search",
                    first_mql_at=AUG,
                    last_mql_at=date(2026, 9, 30),
                ),
                MarketingSpend(period=AUG, region=Region.BRAZIL, amount=Decimal(1000)),
                MarketingSpend(period=SEP, region=Region.BRAZIL, amount=Decimal(2000)),
            ]
        )
        labware = _id(session, "LabWare")
        session.add_all(
            [
                DealCompetition(
                    deal_id="demo-0001",
                    competitor_id=labware,
                    outcome=DealOutcome.LOST,
                    amount=Decimal(50000),
                    closed_at=date(2026, 9, 12),
                ),
                DealCompetition(
                    deal_id="demo-0002",
                    competitor_id=labware,
                    outcome=DealOutcome.WON,
                    closed_at=date(2026, 3, 2),
                ),
            ]
        )
        recent = Signal(
            competitor_id=labware,
            type=SignalType.MESSAGING_CHANGE,
            title="LabWare targets food labs in Brazil",
            summary="LabWare's food page now leads with Brazilian regulation.",
            relevance="Food labs in Brazil, myLIMS's core segment.",
            url="https://labware.test/food",
            detected_at=datetime(2026, 11, 2, tzinfo=UTC),
        )
        session.add_all(
            [
                recent,
                Signal(
                    competitor_id=labware,
                    type=SignalType.EVENT,
                    title="Old event",
                    summary="Too old for the context.",
                    url="https://labware.test/old",
                    detected_at=datetime(2026, 8, 1, tzinfo=UTC),
                ),
            ]
        )
        session.flush()
        return recent.id


class FakeGenerator:
    def __init__(self, *answers: Proposal) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> Proposal:
        self.prompts.append(prompt)
        return self.answers.pop(0)


def _rec(
    action: str, *refs: str, impact: int = 4, confidence: int = 3, cost: int = 2, effort: int = 2
) -> ProposedRecommendation:
    return ProposedRecommendation.model_validate(
        {
            "action": action,
            "evidence": [EvidenceRef(ref=ref, note=f"note on {ref}") for ref in refs],
            "impact": impact,
            "cost": cost,
            "effort": effort,
            "confidence": confidence,
        }
    )


def _run(engine: Engine, generator: FakeGenerator) -> RunResult:
    with Session(engine) as session, session.begin():
        return asyncio.run(generate_recommendations(session, generator, now=NOW))


def test_context_lists_stored_facts_with_references(engine: Engine) -> None:
    signal_id = _fill(engine)
    with Session(engine) as session:
        context = build_context(session, TODAY)
    assert (context.month, context.previous_month) == (SEP, AUG)
    assert list(context.facts) == [f"S{signal_id}", "R1", "R2", "CH1", "CH2", "K1", "D1"]

    brazil = context.facts["R1"]
    assert brazil.text.startswith("Brazil: Sep 2026 MQLs 60, opportunities 6, deals won 1")
    assert "cost per MQL $33.33" in brazil.text
    assert set(brazil.records) == {"funnel_metrics", "marketing_spend"}
    assert len(brazil.records["marketing_spend"]) == 2
    assert "MQL to opportunity 10%" in context.facts["CH1"].text
    assert "won 1, lost 1, win rate 50%" in context.facts["D1"].text
    assert "amount lost to date $50,000" in context.facts["D1"].text

    prompt = context.prompt()
    assert "Internal data: September 2026 (latest month with spend) vs August 2026" in prompt
    assert f"[S{signal_id}] 2026-11-02 LabWare (top 3), messaging change:" in prompt
    assert "Old event" not in prompt  # older than the signal window


def test_stores_valid_recommendations_and_rejects_unsupported_ones(engine: Engine) -> None:
    signal_id = _fill(engine)
    generator = FakeGenerator(
        Proposal(
            recommendations=[
                _rec("Publish a food labs page for Brazil", f"[S{signal_id}]", "r1", "D1"),
                _rec("Invent a fact", "S999"),
                _rec("Trust me"),
            ]
        )
    )
    result = _run(engine, generator)
    assert [r.reason for r in result.rejected] == [
        "evidence not in the stored data: S999",
        "no evidence",
    ]
    assert "<facts>" in generator.prompts[0]

    with Session(engine) as session:
        [rec] = session.scalars(select(Recommendation)).all()
    assert rec.action == "Publish a food labs page for Brazil"
    assert rec.priority == 3.0  # 4 * 3 / (2 + 2), computed in code
    assert rec.status is RecommendationStatus.PROPOSED
    assert rec.prompt_version == PROMPT_VERSION
    signal, region, deals = rec.evidence
    assert signal["ref"] == f"S{signal_id}"
    assert signal["url"] == "https://labware.test/food"
    assert signal["records"] == {"signals": [signal_id]}
    assert region["ref"] == "R1"
    assert region["url"] is None
    assert region["fact"].startswith("Brazil:")
    assert deals["kind"] == "competitor_deals"
    assert len(deals["records"]["deals_competition"]) == 2


def test_keeps_the_top_recommendations_by_priority(engine: Engine) -> None:
    _fill(engine)
    proposals = [_rec(f"Action {n}", "R1", impact=n % 5 + 1) for n in range(6)]
    result = _run(engine, FakeGenerator(Proposal(recommendations=proposals)))
    assert len(result.stored) == MAX_RECOMMENDATIONS
    assert [r.reason for r in result.rejected] == [f"below the top {MAX_RECOMMENDATIONS}"]
    with Session(engine) as session:
        priorities = list(session.scalars(select(Recommendation.priority)))
    assert sorted(priorities) == [0.75, 1.5, 2.25, 3.0, 3.75]  # one of the two 0.75 dropped


def test_a_second_run_the_same_day_keeps_reviewed_ones(engine: Engine) -> None:
    _fill(engine)
    _run(engine, FakeGenerator(Proposal(recommendations=[_rec("A", "R1"), _rec("B", "R2")])))
    with Session(engine) as session, session.begin():
        session.execute(
            update(Recommendation)
            .where(Recommendation.action == "A")
            .values(status=RecommendationStatus.APPROVED)
        )
    result = _run(engine, FakeGenerator(Proposal(recommendations=[_rec("C", "CH1")])))
    assert result.replaced == 1
    with Session(engine) as session:
        actions = session.scalars(select(Recommendation.action).order_by(Recommendation.id))
        assert list(actions) == ["A", "C"]


def test_skips_the_model_without_data(engine: Engine) -> None:
    generator = FakeGenerator()
    result = _run(engine, generator)
    assert result.skipped
    assert generator.prompts == []


def test_weekly_summary_shows_the_latest_recommendations(engine: Engine) -> None:
    signal_id = _fill(engine)
    with Session(engine) as session, session.begin():
        old = Recommendation(
            action="Last week's idea", impact=5, cost=1, effort=1, confidence=5, evidence=[]
        )
        old.created_at = datetime(2026, 10, 30, 9, tzinfo=UTC)
        rejected = Recommendation(
            action="Rejected idea", impact=5, cost=1, effort=1, confidence=5, evidence=[]
        )
        rejected.status = RecommendationStatus.REJECTED
        session.add_all([old, rejected])
    _run(engine, FakeGenerator(Proposal(recommendations=[_rec("Do it", f"S{signal_id}", "R1")])))

    with Session(engine) as session:
        report = build_weekly_report(session, TODAY)
    assert [r.action for r in report.recommendations] == ["Do it"]
    markdown = render_markdown(report)
    assert "## Recommendations (generated" in markdown
    assert "1. **Do it**" in markdown
    assert "Priority 3.00: impact 4, confidence 3, cost 2, effort 2." in markdown
    assert (
        "   - [LabWare targets food labs in Brazil](https://labware.test/food): "
        f"note on S{signal_id}" in markdown
    )
    assert "   - Brazil funnel and spend: note on R1" in markdown


def test_weekly_summary_without_recommendations(engine: Engine) -> None:
    with Session(engine) as session:
        markdown = render_markdown(build_weekly_report(session, TODAY))
    assert "No recommendations this week." in markdown

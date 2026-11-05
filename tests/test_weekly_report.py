"""Weekly summary (guide Step 6) on SQLite with a small hand-made dataset."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.orm import Session

from scout_ai.db.models import (
    Competitor,
    DealCompetition,
    DealOutcome,
    FunnelMetric,
    MarketingSpend,
    Region,
    Signal,
    SignalType,
    WeeklySummary,
)
from scout_ai.db.setup import setup_database
from scout_ai.reports.weekly import (
    DEMO_LABEL,
    build_weekly_report,
    render_markdown,
    save_summary,
)

AUG, SEP, OCT = date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)
REPORT_DATE = date(2026, 11, 5)


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


def _funnel(period: date, region: Region, channel: str, *counts: int) -> FunnelMetric:
    mqls, opportunities, deals_won = (*counts, 0, 0, 0)[:3]
    return FunnelMetric(
        period=period,
        region=region,
        channel=channel,
        mqls=mqls,
        opportunities=opportunities,
        deals_won=deals_won,
    )


def _deal(
    deal_id: str, competitor_id: int, outcome: DealOutcome, closed: date | None
) -> DealCompetition:
    return DealCompetition(
        deal_id=deal_id, competitor_id=competitor_id, outcome=outcome, closed_at=closed
    )


def _fill(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                _funnel(AUG, Region.BRAZIL, "Paid Search", 50, 10, 2),
                _funnel(SEP, Region.BRAZIL, "Paid Search", 60, 6, 1),
                _funnel(SEP, Region.BRAZIL, "", 40, 4, 1),
                _funnel(SEP, Region.EMEA, "Referrals", 10),
                # October is in progress: no spend yet, so it must not be the report month.
                _funnel(OCT, Region.BRAZIL, "Paid Search", 0, 99),
                MarketingSpend(period=AUG, region=Region.BRAZIL, amount=Decimal(1000)),
                MarketingSpend(period=SEP, region=Region.BRAZIL, amount=Decimal(2000)),
                MarketingSpend(period=SEP, region=Region.NORTH_AMERICA, amount=Decimal(500)),
            ]
        )
        labware = _id(session, "LabWare")
        session.add_all(
            [
                _deal("d1", labware, DealOutcome.WON, date(2026, 9, 10)),
                _deal("d2", labware, DealOutcome.LOST, date(2026, 3, 1)),
                _deal("d3", labware, DealOutcome.LOST, date(2026, 10, 2)),  # after the month
                _deal("d4", labware, DealOutcome.LOST, date(2025, 12, 20)),  # last year
                _deal("d5", labware, DealOutcome.OPEN, None),
            ]
        )
        session.add_all(
            [
                Signal(
                    competitor_id=_id(session, "Clinisys"),
                    type=SignalType.PRESS_RELEASE,
                    title="Clinisys launches an AI platform",
                    summary="Clinisys announced an AI platform.",
                    url="https://clinisys.test/ai",
                    detected_at=datetime(2026, 11, 3, 12, tzinfo=UTC),
                ),
                Signal(
                    competitor_id=labware,
                    type=SignalType.EVENT,
                    title="LabWare at a trade show",
                    summary="LabWare will exhibit.",
                    relevance="Food labs.",
                    url="https://labware.test/show",
                    detected_at=datetime(2026, 10, 1, tzinfo=UTC),  # older than a week
                ),
            ]
        )


def test_report_uses_the_latest_month_with_spend(engine: Engine) -> None:
    _fill(engine)
    with Session(engine) as session:
        report = build_weekly_report(session, REPORT_DATE)
    assert (report.month, report.previous_month) == (SEP, AUG)

    brazil_now, brazil_before = report.regions["Brazil"]
    assert (brazil_now.mqls, brazil_now.opportunities, brazil_now.deals_won) == (100, 10, 2)
    assert brazil_now.cost_per_mql == Decimal(20)
    assert brazil_now.opportunities_per_1k == Decimal(5)
    assert brazil_now.cac == Decimal(1000)
    assert brazil_before.cost_per_mql == Decimal(20)

    # Spend without funnel rows, and funnel rows without spend, both show up.
    assert report.regions["North America"][0].spend == Decimal(500)
    assert report.regions["EMEA"][0].spend is None
    assert report.regions["EMEA"][0].cost_per_mql is None

    assert list(report.channels) == ["Paid Search", "(no channel)", "Referrals"]


def test_competitor_deals_and_signals(engine: Engine) -> None:
    _fill(engine)
    with Session(engine) as session:
        report = build_weekly_report(session, REPORT_DATE)
    labware = next(c for c in report.competitors if c.name == "LabWare")
    assert (labware.won_month, labware.lost_month) == (1, 0)
    assert (labware.won_ytd, labware.lost_ytd, labware.open_now) == (1, 1, 1)
    assert labware.win_rate_ytd == 0.5
    assert [c.name for c in report.competitors][:3] == ["Clinisys", "LabWare", "STARLIMS"]

    assert [s.title for s in report.signals] == ["Clinisys launches an AI platform"]


def test_markdown(engine: Engine) -> None:
    _fill(engine)
    with Session(engine) as session:
        markdown = render_markdown(build_weekly_report(session, REPORT_DATE))
    assert markdown.startswith("# Scout AI weekly summary: 2026-11-05")
    assert DEMO_LABEL in markdown
    assert "## Competitor signals (Oct 29 to Nov 04)" in markdown
    assert "### Clinisys (top 3): 1 new" in markdown
    assert "[press release] [Clinisys launches an AI platform](https://clinisys.test/ai)" in (
        markdown
    )
    assert "September 2026 vs August 2026" in markdown
    assert "| Brazil | 100 (+100%) | 10 (+0%) | 2 (+0%) | $2,000 (+100%) | $20 (+0%)" in markdown
    assert "| LabWare | 1 | 0 | 1 | 1 | 50% | 1 |" in markdown
    assert "| Paid Search | 60 (+20%) | 6 (-40%) | 1 (-50%) | 10% (-10 pp) |" in markdown


def test_markdown_without_internal_data(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(Signal))
    with Session(engine) as session:
        markdown = render_markdown(build_weekly_report(session, REPORT_DATE))
    assert "No new signals this week." in markdown
    assert "No internal data loaded yet." in markdown


def test_save_summary_replaces_the_same_day(engine: Engine) -> None:
    _fill(engine)
    with Session(engine) as session, session.begin():
        report = build_weekly_report(session, REPORT_DATE)
        first = save_summary(session, report, "first")
        second = save_summary(session, report, render_markdown(report))
        assert first.id == second.id
    with Session(engine) as session:
        [summary] = session.scalars(select(WeeklySummary)).all()
    assert summary.title == "Scout AI weekly summary: 2026-11-05"
    assert (summary.report_date, summary.month, summary.signal_count) == (REPORT_DATE, SEP, 1)
    assert summary.markdown.startswith("# Scout AI weekly summary: 2026-11-05")

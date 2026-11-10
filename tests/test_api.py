"""The dashboard API (guide Step 10) on SQLite, through FastAPI's test client."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from scout_ai.api import create_app
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
from scout_ai.db.setup import setup_database

AUG, SEP = date(2026, 8, 1), date(2026, 9, 1)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    engine = create_engine(url)
    _fill(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(create_app(engine))


def _fill(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        labware = session.scalar(select(Competitor).where(Competitor.name == "LabWare"))
        assert labware is not None
        campaign = Campaign(name="Food Labs Webinar", channel="Events")
        session.add_all(
            [
                campaign,
                FunnelMetric(
                    period=SEP,
                    region=Region.BRAZIL,
                    channel="Events",
                    campaign="Food Labs Webinar",
                    mqls=40,
                    opportunities=4,
                    deals_won=2,
                ),
                FunnelMetric(
                    period=SEP,
                    region=Region.LATAM,
                    channel="Paid Search",
                    campaign="",
                    mqls=10,
                    opportunities=1,
                ),
                FunnelMetric(
                    period=AUG,
                    region=Region.BRAZIL,
                    channel="Events",
                    campaign="Food Labs Webinar",
                    mqls=20,
                    opportunities=2,
                ),
                MarketingSpend(period=SEP, region=Region.BRAZIL, amount=Decimal(2000)),
                MarketingSpend(period=AUG, region=Region.BRAZIL, amount=Decimal(1000)),
                DealCompetition(
                    deal_id="demo-1",
                    competitor=labware,
                    outcome=DealOutcome.WON,
                    amount=Decimal(10000),
                    closed_at=date(2026, 9, 10),
                ),
                DealCompetition(
                    deal_id="demo-2",
                    competitor=labware,
                    outcome=DealOutcome.LOST,
                    closed_at=date(2026, 9, 12),
                ),
                DealCompetition(deal_id="demo-3", competitor=labware, outcome=DealOutcome.OPEN),
                Signal(
                    competitor=labware,
                    type=SignalType.EVENT,
                    title="LabWare food webinar",
                    summary="A webinar for food labs.",
                    url="https://labware.test/webinar",
                    detected_at=datetime(2026, 11, 2, tzinfo=UTC),
                ),
                WeeklySummary(
                    report_date=date(2026, 11, 6),
                    title="Scout AI weekly summary: 2026-11-06",
                    signal_count=1,
                    markdown="# Scout AI weekly summary\n",
                ),
            ]
        )
        session.flush()
        session.add(
            Recommendation(
                action="Invite food labs to a myLIMS webinar",
                evidence=[
                    {
                        "ref": "K1",
                        "kind": "campaign",
                        "label": "Food Labs Webinar campaign",
                        "fact": "Food Labs Webinar: Sep 2026 MQLs 40",
                        "note": "Webinars bring food labs.",
                        "url": None,
                        "records": {"campaigns": [campaign.id]},
                    }
                ],
                impact=4,
                cost=2,
                effort=2,
                confidence=3,
            )
        )


def test_serves_the_front_end(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "/static/app.js" in page.text
    assert client.get("/static/markdown.js").status_code == 200


def test_meta_lists_months_and_the_banner(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["months"] == ["2026-08-01", "2026-09-01"]
    assert meta["latest_spend_month"] == "2026-09-01"
    assert meta["banner"].startswith("Synthetic demo data")


def test_signals_filter_by_competitor_and_type(client: TestClient) -> None:
    [signal] = client.get("/api/signals", params={"competitor": "LabWare"}).json()
    assert signal["title"] == "LabWare food webinar"
    assert client.get("/api/signals", params={"competitor": "STARLIMS"}).json() == []
    assert client.get("/api/signals", params={"type": "pricing"}).json() == []
    assert client.get("/api/signals", params={"since": "2026-11-03"}).json() == []


def test_funnel_groups_by_month_and_dimension(client: TestClient) -> None:
    rows = client.get("/api/funnel", params={"by": "region", "from": "2026-09-01"}).json()
    assert [(r["group"], r["mqls"]) for r in rows] == [("Brazil", 40), ("Latam", 10)]
    rows = client.get("/api/funnel", params={"by": "campaign", "region": "brazil"}).json()
    assert [(r["period"], r["group"]) for r in rows] == [
        ("2026-08-01", "Food Labs Webinar"),
        ("2026-09-01", "Food Labs Webinar"),
    ]
    totals = client.get("/api/funnel", params={"by": "total"}).json()
    assert [r["opportunities"] for r in totals] == [2, 5]


def test_spend_has_cost_metrics_per_region(client: TestClient) -> None:
    rows = client.get("/api/spend").json()
    assert [(r["period"], r["region"]) for r in rows] == [
        ("2026-08-01", "brazil"),
        ("2026-09-01", "brazil"),
    ]
    sep = rows[1]
    assert sep["cost_per_mql"] == 50.0
    assert sep["opportunities_per_1k"] == 2.0
    assert sep["cac"] == 1000.0
    assert rows[0]["cac"] is None  # no deal won in August


def test_campaigns_and_competitive_deals(client: TestClient) -> None:
    [campaign] = client.get("/api/campaigns").json()
    assert (campaign["name"], campaign["mqls"], campaign["deals_won"]) == (
        "Food Labs Webinar",
        60,
        2,
    )
    deals = client.get("/api/deals/competition").json()
    assert deals["year"] == 2026
    [labware] = deals["competitors"]
    assert (labware["won"], labware["lost"], labware["open"]) == (1, 1, 1)
    assert labware["win_rate"] == 0.5
    assert labware["amount_won"] == 10000.0


def test_approving_returns_the_dry_run_and_is_stored(client: TestClient, engine: Engine) -> None:
    [rec] = client.get("/api/recommendations", params={"status": "proposed"}).json()
    response = client.patch(f"/api/recommendations/{rec['id']}", json={"status": "approved"})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["recommendation"]["status"] == "approved"
    assert body["clickup_task"]["name"] == "Invite food labs to a myLIMS webinar"
    assert body["hubspot_tags"] == [
        {"campaign": "Food Labs Webinar", "tag": f"scout-ai-rec-{rec['id']}"}
    ]
    with Session(engine) as session:
        stored = session.get(Recommendation, rec["id"])
        assert stored is not None and stored.status is RecommendationStatus.APPROVED

    again = client.patch(f"/api/recommendations/{rec['id']}", json={"status": "rejected"})
    assert again.status_code == 409
    missing = client.patch("/api/recommendations/999", json={"status": "approved"})
    assert missing.status_code == 404
    invalid = client.patch(f"/api/recommendations/{rec['id']}", json={"status": "done"})
    assert invalid.status_code == 422


def test_notifications_list_and_detail(client: TestClient) -> None:
    [item] = client.get("/api/notifications").json()
    assert item["report_date"] == "2026-11-06"
    assert "markdown" not in item
    detail = client.get(f"/api/notifications/{item['id']}").json()
    assert detail["markdown"].startswith("# Scout AI weekly summary")
    assert client.get("/api/notifications/999").status_code == 404

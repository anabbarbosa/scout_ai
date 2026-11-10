"""Approving and rejecting recommendations (guide Step 8), dry run, on SQLite."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from scout_ai.cli import main
from scout_ai.config import get_settings
from scout_ai.db.models import Campaign, Recommendation, RecommendationStatus
from scout_ai.db.session import get_engine
from scout_ai.db.setup import setup_database
from scout_ai.review import CLICKUP_TAG, ReviewError, approve, reject


@pytest.fixture
def url(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    return url


@pytest.fixture
def engine(url: str) -> Iterator[Engine]:
    engine = create_engine(url)
    yield engine
    engine.dispose()


def _recommendation(engine: Engine) -> int:
    """Store one proposed recommendation citing a signal and two campaigns."""
    with Session(engine) as session, session.begin():
        webinar = Campaign(name="Food Labs Webinar", channel="Events")
        ads = Campaign(name="Agro Ads", channel="Paid Search")
        session.add_all([webinar, ads])
        session.flush()
        rec = Recommendation(
            action="Publish a myLIMS vs LabWare page for food labs in Brazil",
            evidence=[
                {
                    "ref": "S1",
                    "kind": "signal",
                    "label": "LabWare launches a food page",
                    "fact": "2026-11-02 LabWare (top 3), messaging change: food page.",
                    "note": "LabWare is targeting our strongest segment.",
                    "url": "https://labware.test/food",
                    "records": {"signals": [1]},
                },
                {
                    "ref": "K1",
                    "kind": "campaign",
                    "label": "Food Labs Webinar campaign",
                    "fact": "Food Labs Webinar (Events): Sep 2026 MQLs 60",
                    "note": "Food labs answer our campaigns.",
                    "url": None,
                    "records": {"campaigns": [webinar.id, ads.id], "funnel_metrics": [3]},
                },
            ],
            impact=4,
            cost=2,
            effort=2,
            confidence=3,
        )
        session.add(rec)
        session.flush()
        return rec.id


def test_approve_builds_the_task_and_campaign_tags(engine: Engine) -> None:
    rec_id = _recommendation(engine)
    with Session(engine) as session, session.begin():
        review = approve(session, rec_id)
        assert review.dry_run
        assert review.task is not None
        body = review.task.body()
        assert body["name"] == "Publish a myLIMS vs LabWare page for food labs in Brazil"
        assert body["tags"] == [CLICKUP_TAG, f"scout-ai-rec-{rec_id}"]
        description = body["markdown_description"]
        assert "priority 3.00" in description
        assert "Impact 4/5 · Confidence 3/5 · Cost 2/5 · Effort 2/5" in description
        assert "[LabWare launches a food page](https://labware.test/food)" in description
        assert "**Food Labs Webinar campaign**: Food labs answer our campaigns." in description
        assert "synthetic demo data" in description
        assert [(t.campaign, t.tag) for t in review.tags] == [
            ("Agro Ads", f"scout-ai-rec-{rec_id}"),
            ("Food Labs Webinar", f"scout-ai-rec-{rec_id}"),
        ]

    with Session(engine) as session:
        rec = session.get(Recommendation, rec_id)
        assert rec is not None
        assert rec.status is RecommendationStatus.APPROVED
        assert rec.clickup_task_id is None  # dry run: no real task


def test_reject_and_review_only_once(engine: Engine) -> None:
    rec_id = _recommendation(engine)
    with Session(engine) as session, session.begin():
        review = reject(session, rec_id)
        assert review.task is None and review.tags == []
    with Session(engine) as session:
        with pytest.raises(ReviewError, match="already rejected"):
            approve(session, rec_id)
        with pytest.raises(ReviewError, match="not found"):
            reject(session, rec_id + 1)


def test_cli_approve_prints_the_dry_run(
    url: str,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rec_id = _recommendation(engine)
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        assert main(["approve", str(rec_id)]) == 0
        out = capsys.readouterr().out
        assert "Dry run, ClickUp task that would be created:" in out
        assert f"Food Labs Webinar: scout-ai-rec-{rec_id}" in out

        assert main(["reject", str(rec_id)]) == 1
        assert "already approved" in capsys.readouterr().err
    finally:
        get_engine().dispose()
        get_settings.cache_clear()
        get_engine.cache_clear()

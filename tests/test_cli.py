from collections.abc import Iterator
from pathlib import Path

import pytest

from scout_ai.cli import COMMANDS, main
from scout_ai.config import get_settings
from scout_ai.db.session import get_engine


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    """Point the settings at an empty tmp_path, ignoring any local .env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path / "demo"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_every_guide_command_is_registered() -> None:
    assert set(COMMANDS) == {
        "db-setup",
        "collect",
        "analyze",
        "fetch",
        "load",
        "recommend",
        "approve",
        "reject",
        "report",
        "serve",
    }


def test_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_fetch_requires_a_token(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch"]) == 1
    assert "HUBSPOT_TOKEN" in capsys.readouterr().err


def test_fetch_requires_the_marketing_csvs(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setenv("HUBSPOT_TOKEN", "test-token")
    get_settings.cache_clear()
    assert main(["fetch"]) == 1
    assert "Monthly MQL Cost Summary" in capsys.readouterr().err


def test_load_reports_a_missing_dataset(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setenv("DATABASE_URL", "sqlite:///unused.db")
    get_settings.cache_clear()
    assert main(["load"]) == 1
    assert "manifest.json" in capsys.readouterr().err


def test_report_stores_the_summary_and_writes_the_file(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from scout_ai.db.models import WeeklySummary
    from scout_ai.db.setup import setup_database

    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    env.setenv("DATABASE_URL", url)
    env.setenv("REPORT_DIR", str(tmp_path / "reports"))
    get_settings.cache_clear()
    get_engine.cache_clear()

    assert main(["report"]) == 0
    assert main(["report"]) == 0  # same day: replaced, not duplicated
    [path] = (tmp_path / "reports").glob("weekly-*.md")
    markdown = path.read_text(encoding="utf-8")
    assert markdown.startswith("# Scout AI weekly summary")
    with Session(get_engine()) as session:
        [summary] = session.scalars(select(WeeklySummary)).all()
    assert summary.markdown == markdown


def test_recommend_skips_an_empty_database(
    env: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scout_ai.db.setup import setup_database

    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)  # competitors and sources only: no signals, no internal data
    env.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()

    assert main(["recommend"]) == 0  # the model is not called
    assert "Nothing to recommend" in capsys.readouterr().out

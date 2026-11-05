from collections.abc import Iterator
from pathlib import Path

import pytest

from scout_ai.cli import COMMANDS, main
from scout_ai.config import get_settings
from scout_ai.db.session import get_engine

IMPLEMENTED = {"db-setup", "collect", "analyze", "fetch", "load"}


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


@pytest.mark.parametrize("command", sorted(set(COMMANDS) - IMPLEMENTED))
def test_stub_commands_are_registered(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([command]) == 1
    assert "not implemented yet" in capsys.readouterr().out


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

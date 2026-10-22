import pytest

from scout_ai.config import Settings


def test_defaults_to_local_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///scout_ai.db"
    assert settings.hubspot_token is None


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/scout_ai")
    monkeypatch.setenv("HUBSPOT_TOKEN", "secret-token")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://localhost/scout_ai"
    assert settings.hubspot_token is not None
    assert settings.hubspot_token.get_secret_value() == "secret-token"
    assert "secret-token" not in repr(settings)

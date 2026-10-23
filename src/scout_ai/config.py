"""Application settings loaded from environment variables or a local .env file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local PostgreSQL from docker/compose.yml
    database_url: str = "postgresql+psycopg://scout:scout@localhost:5434/scout_ai"

    claude_code_oauth_token: SecretStr | None = None

    hubspot_token: SecretStr | None = None

    clickup_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Application settings loaded from environment variables or a local .env file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///scout_ai.db"

    anthropic_api_key: SecretStr | None = None

    hubspot_token: SecretStr | None = None

    clickup_token: SecretStr | None = None
    clickup_list_id: str | None = None

    powerbi_tenant_id: str | None = None
    powerbi_client_id: str | None = None
    powerbi_client_secret: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

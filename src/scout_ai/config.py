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

    # Synthetic demo dataset (guide Step 5): same seed + same input = same files
    demo_seed: int = 42
    demo_data_dir: str = "data/demo"
    # Marketing CSV exports read by `scout fetch`; they hold personal data, never commit them
    raw_data_dir: str = "data/raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()

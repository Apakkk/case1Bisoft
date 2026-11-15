"""Application settings, read from environment variables and the .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    database_url: str = "postgresql://carrier:carrier@localhost:5433/carrier"

    typesafe_api_key: SecretStr | None = None
    jev_model: str | None = "jev-1.14.0"  # the confidence thresholds were measured on this version
    jev_timeout_seconds: float = 5.0

    ors_api_key: SecretStr | None = None

    rules_path: Path = Path("config/rules.yaml")
    config_dir: Path = Path("config")  # distances.yaml, cities.csv, city_aliases.yaml


@lru_cache
def get_settings() -> Settings:
    return Settings()

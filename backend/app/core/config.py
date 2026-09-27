"""Application configuration settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings class reading from environment variables."""

    APP_ENV: Literal["development", "production", "test"] = "development"
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/hiring_radar"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of the settings."""
    return Settings()

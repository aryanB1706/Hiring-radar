"""Application configuration settings."""

from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Central settings class reading from environment variables."""

    APP_ENV: Literal["development", "production", "test"] = "development"
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/hiring_radar"
    LOG_LEVEL: str = "INFO"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    RSS_FEEDS: str = (
        "https://weworkremotely.com/categories/remote-programming-jobs.rss,"
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of the settings."""
    return Settings()


def get_rss_feeds() -> list[str]:
    """Return the configured RSS feed URLs as a list."""
    return [feed.strip() for feed in get_settings().RSS_FEEDS.split(",") if feed.strip()]

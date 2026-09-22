from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.pricing import ModelPrice

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # repo-root .env, whatever the cwd


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://hiring:hiring@localhost:5434/hiring_radar"
    redis_url: str = "redis://localhost:6380/0"
    log_level: str = "INFO"

    # LLM gateway (see app/llm). Model names come only from here.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_fast_model: str = "gemini-3.5-flash-lite"
    llm_rpm_limit: int = 5  # placeholder: check your free-tier limit in Google AI Studio
    llm_cache_ttl_seconds: int = 86400  # 0 disables the response cache
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 60.0
    llm_pricing: dict[str, ModelPrice] = {}  # JSON: {"<model>": {"input_per_mtok": .., ...}}

    # Collectors (see app/collectors)
    http_user_agent: str = (
        "HiringRadar/0.1 (+https://github.com/aryanB1706/Hiring-radar; portfolio project)"
    )
    http_timeout_seconds: float = 20.0
    http_min_delay_seconds: float = 1.0  # minimum gap between requests to the same host
    reddit_client_id: str | None = None
    reddit_client_secret: SecretStr | None = None
    reddit_user_agent: str = "script:hiring-radar:0.1 (by /u/your_reddit_username)"
    subreddits: str = "forhire,hiring,developersIndia,remotepython"  # comma-separated
    ingest_interval_hours: float = 6.0

    @property
    def subreddit_list(self) -> list[str]:
        names = (name.strip().removeprefix("r/") for name in self.subreddits.split(","))
        return [name for name in names if name]


@lru_cache
def get_settings() -> Settings:
    return Settings()

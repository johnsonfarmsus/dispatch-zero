from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    session_secret: str = Field(min_length=32)
    app_env: str = "development"
    log_level: str = "INFO"

    # Sessions
    session_cookie_name: str = "dz_session"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Auth rate limit (login only)
    login_rate_limit_max: int = 5
    login_rate_limit_window_seconds: int = 60 * 15  # 15 min


@lru_cache
def get_settings() -> Settings:
    return Settings()

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

    # Ollama Cloud
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_model: str = "gpt-oss:120b"
    ollama_timeout_seconds: int = 15

    # Photo capture and verification
    photo_upload_dir: str = "/uploads"
    photo_max_dimension: int = 600
    photo_jpeg_quality: int = 70
    exif_freshness_window_seconds: int = 600  # 10 min
    gps_verification_radius_m: int = 80  # single radius for all categories


@lru_cache
def get_settings() -> Settings:
    return Settings()

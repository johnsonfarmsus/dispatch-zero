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

    # Briefing AI — any OpenAI-compatible chat endpoint.
    # Defaults point at Ollama Cloud's hosted gemma4:31b-cloud (a smaller,
    # open-weight model than the previous gpt-oss:120b default — closer in
    # spirit to the self-hosted OLMo 2 production target). Production
    # overrides via env to a self-hosted OLMo 2 13B endpoint over Tailscale.
    # Timeout is set generously (60s) so a slow inference box doesn't fail
    # mid-briefing — cloud overrides this in dev/.env if it wants tighter.
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_model: str = "gemma4:31b-cloud"
    ollama_timeout_seconds: int = 60

    # Photo capture and verification
    photo_upload_dir: str = "/uploads"
    photo_max_dimension: int = 600
    photo_jpeg_quality: int = 70
    exif_freshness_window_seconds: int = 600  # 10 min
    gps_verification_radius_m: int = 80  # single radius for all categories

    # Rate limits — bounds on expensive endpoints.
    rate_limit_mission_request_per_day: int = 50
    rate_limit_mission_generate_per_day: int = 50
    rate_limit_signup_per_ip_per_hour: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()

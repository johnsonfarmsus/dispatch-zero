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
    #
    # Default: a locally-running Ollama instance serving olmo2:13b. Matches
    # the canonical-instance production setup (which uses Ollama over Tailscale
    # to a separate inference box) and aligns with the project's AGPL stance —
    # OLMo 2 is the most-open model available (Apache-2.0 weights + open
    # training data + open training code).
    #
    # For local dev with docker compose: .env.example overrides this default
    # to http://host.docker.internal:11434/v1 so the app container can reach
    # Ollama running on the host.
    #
    # Cloud fallback (paid): set OLLAMA_BASE_URL=https://ollama.com/v1 +
    # OLLAMA_MODEL=gemma4:31b-cloud + a real OLLAMA_API_KEY.
    #
    # Timeout is generous (60s) — a slow inference box can take 25-40s per
    # briefing and 15s was clipping it.
    ollama_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "olmo2:13b"
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

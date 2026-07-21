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
    # Timeout is generous (120s). A slow inference box takes 25-40s per
    # briefing, and when the GPU is shared the model can be evicted between
    # requests — a cold call then pays a reload (~10-30s) on top, which was
    # blowing past a 60s ceiling and surfacing as a spurious 503.
    ollama_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "olmo2:13b"
    # Availability floor for the shared-GPU box: when the primary model fails
    # (evicted under contention, mid-reload, or persistently erroring), one
    # retry runs against this smaller model on the same endpoint. olmo2:7b
    # reloads in seconds where the 13B pays 10-30s, so it usually answers
    # even while the box is thrashing. Empty string disables the fallback.
    ollama_fallback_model: str = "olmo2:7b"
    ollama_timeout_seconds: int = 120

    # Photo capture and verification
    photo_upload_dir: str = "/uploads"
    photo_max_dimension: int = 600
    photo_jpeg_quality: int = 70
    exif_freshness_window_seconds: int = 600  # 10 min
    gps_verification_radius_m: int = 80  # single radius for all categories
    # Upload abuse bounds. A phone photo is a few MB; 15 MB is generous
    # headroom while still rejecting multi-hundred-MB bodies before we
    # read them fully into memory. photo_max_pixels caps the DECODED
    # dimensions to defeat decompression bombs (a few-KB PNG that expands
    # to gigabytes of RAM). 40 MP comfortably exceeds any real phone
    # camera (a 108 MP shot downscales fine; we only need enough detail
    # for a 600px thumbnail anyway).
    photo_max_upload_bytes: int = 15 * 1024 * 1024
    photo_max_pixels: int = 40_000_000

    # Rate limits — bounds on expensive endpoints.
    rate_limit_mission_request_per_day: int = 50
    rate_limit_mission_generate_per_day: int = 50
    rate_limit_signup_per_ip_per_hour: int = 10
    # Community submissions are cheap for the user but trigger a Place +
    # Submission row, Pillow card composition, and an outbound Overpass
    # pre-flight per call. Cap per-user per-day so one account can't flood
    # the review queue or get our server IP rate-limited by Overpass.
    rate_limit_submission_per_day: int = 30

    # ---- OSM integration ----
    # OAuth 2.0 client registered at openstreetmap.org/oauth2/applications.
    # Empty by default so dev/test environments without OSM creds boot fine —
    # the admin "Connect OSM" path is what catches the missing creds.
    osm_client_id: str = ""
    osm_client_secret: str = ""
    # When true, publish_to_osm builds the changeset XML and records an
    # osm_publications row with dry_run=true but does NOT make any HTTP
    # call to OSM. Lets us verify the round-trip (OAuth + tag mapping +
    # XML construction) before any real edit lands. Flip to false when
    # you've eyeballed enough dry-run output to trust the pipeline.
    osm_dry_run: bool = True
    # OSM API host + OAuth endpoints. Always production (no separate dev
    # server config) — dry-run mode is the safety lever.
    osm_base_url: str = "https://api.openstreetmap.org"
    osm_oauth_base_url: str = "https://www.openstreetmap.org"
    # Daily cap on REAL publishes (dry-run rows don't count). Hit it and
    # the Approve+OSM button is disabled until tomorrow UTC; regular
    # Approve still works.
    osm_daily_publish_cap: int = 5
    # User-Agent string on every OSM HTTP call. OSM admins watch for
    # apps that don't identify themselves; this is how we stay above
    # board. Bump the version on substantive logic changes.
    osm_user_agent: str = "Dispatch Zero/0.1 (https://dispatchzero.ataary.com)"
    # Public URL of this app, used to build the OAuth redirect URI sent
    # to OSM during the connect flow. MUST match what's registered on the
    # OSM app: redirect_uri value goes through verbatim.
    osm_redirect_uri: str = "https://dispatchzero.ataary.com/admin/osm/callback"

    # ---- Localization / data-source defaults ----
    # These parameterize US-centric defaults so non-US self-hosters aren't
    # blocked by hardcoded assumptions. UI + briefings remain English; this
    # is about which slice of the open data the discovery engine reads.
    #
    # Wikipedia geosearch + extract language. Drives both the API host
    # (<lang>.wikipedia.org) and the wikipedia= OSM tag prefix.
    wikipedia_language: str = "en"
    # Default religion= tag when publishing a place_of_worship to OSM. Rural
    # US coverage is overwhelmingly Christian; set to "" to omit the tag and
    # let OSM mappers fill it, or to another value for a different region.
    osm_default_religion: str = "christian"


@lru_cache
def get_settings() -> Settings:
    return Settings()

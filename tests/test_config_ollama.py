from dispatchzero.config import Settings


def test_ollama_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    # Clear any prod overrides leaking via docker env so we test pure defaults
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
    s = Settings()
    assert s.ollama_api_key == "test-key"
    # Default points at a locally-running Ollama instance (the canonical
    # production setup) rather than a paid cloud endpoint. .env.example
    # overrides the URL to host.docker.internal for the docker-compose dev
    # workflow; this assertion checks the raw code default for the case
    # where someone runs the app directly (no docker, no .env).
    assert s.ollama_base_url == "http://localhost:11434/v1"
    assert s.ollama_model == "olmo2:13b"
    # Bumped from 15s to 60s when production switched to self-hosted OLMo 2 —
    # a slow inference box can take 15-40s per briefing and 15s was clipping it.
    assert s.ollama_timeout_seconds == 60

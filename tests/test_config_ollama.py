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
    monkeypatch.delenv("OLLAMA_FALLBACK_MODEL", raising=False)
    s = Settings()
    assert s.ollama_api_key == "test-key"
    # Default points at a locally-running Ollama instance (the canonical
    # production setup) rather than a paid cloud endpoint. .env.example
    # overrides the URL to host.docker.internal for the docker-compose dev
    # workflow; this assertion checks the raw code default for the case
    # where someone runs the app directly (no docker, no .env).
    assert s.ollama_base_url == "http://localhost:11434/v1"
    assert s.ollama_model == "olmo2:13b"
    # 15s -> 60s when production switched to self-hosted OLMo 2, then 60s -> 120s
    # because the shared GPU box can evict the model and pay a reload (~10-30s)
    # on top of a 25-40s briefing — 60s was surfacing as spurious 503s.
    assert s.ollama_timeout_seconds == 120
    # Availability floor: when the 13B is evicted/unreachable, one retry runs
    # against the smaller olmo on the same box (reloads in seconds).
    assert s.ollama_fallback_model == "olmo2:7b"

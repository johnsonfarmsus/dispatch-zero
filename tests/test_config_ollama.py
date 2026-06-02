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
    assert s.ollama_base_url == "https://ollama.com/v1"
    assert s.ollama_model == "gpt-oss:120b"
    # Bumped from 15s to 60s when production switched to self-hosted OLMo 2 —
    # a slow inference box can take 15-40s per briefing and 15s was clipping it.
    assert s.ollama_timeout_seconds == 60

from dispatchzero.config import Settings


def test_ollama_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    s = Settings()
    assert s.ollama_api_key == "test-key"
    assert s.ollama_base_url == "https://ollama.com/v1"
    assert s.ollama_model == "gpt-oss:120b"
    assert s.ollama_timeout_seconds == 15

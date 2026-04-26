from dispatchzero.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    settings = Settings()
    assert str(settings.database_url) == "postgresql+asyncpg://u:p@db:5432/x"
    assert str(settings.redis_url) == "redis://redis:6379/0"
    assert settings.session_secret == "x" * 32
    assert settings.app_env == "development"  # default

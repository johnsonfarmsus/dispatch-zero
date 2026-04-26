from dispatchzero.config import Settings


def test_session_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    s = Settings()
    assert s.session_cookie_name == "dz_session"
    assert s.session_cookie_max_age_seconds == 60 * 60 * 24 * 30  # 30 days
    assert s.login_rate_limit_max == 5
    assert s.login_rate_limit_window_seconds == 60 * 15

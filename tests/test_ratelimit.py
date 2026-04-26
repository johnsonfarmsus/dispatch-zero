import asyncio

import pytest

from dispatchzero.auth.ratelimit import LoginRateLimiter


@pytest.mark.asyncio
async def test_first_n_attempts_allowed(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=3, window_seconds=60)
    for _ in range(3):
        assert await limiter.is_allowed("1.2.3.4") is True
        await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False


@pytest.mark.asyncio
async def test_different_ips_independent(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=2, window_seconds=60)
    for _ in range(2):
        await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False
    assert await limiter.is_allowed("5.6.7.8") is True


@pytest.mark.asyncio
async def test_window_expires(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=1, window_seconds=1)
    await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False
    await asyncio.sleep(1.1)
    assert await limiter.is_allowed("1.2.3.4") is True

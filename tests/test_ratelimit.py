import asyncio

import pytest

from dispatchzero.auth.ratelimit import LoginRateLimiter
from dispatchzero.ratelimit import check_and_increment, RateLimitExceeded


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


@pytest.mark.asyncio
async def test_first_call_in_window_passes(redis_client):
    await check_and_increment(
        redis=redis_client, scope="test", identifier="user-1",
        max_count=3, window_seconds=60,
    )


@pytest.mark.asyncio
async def test_caps_at_max_count(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-2",
            max_count=3, window_seconds=60,
        )
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-2",
            max_count=3, window_seconds=60,
        )
    assert exc_info.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_separate_identifiers_have_separate_buckets(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-A",
            max_count=3, window_seconds=60,
        )
    await check_and_increment(
        redis=redis_client, scope="test", identifier="user-B",
        max_count=3, window_seconds=60,
    )


@pytest.mark.asyncio
async def test_separate_scopes_have_separate_buckets(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="scope-A", identifier="user-1",
            max_count=3, window_seconds=60,
        )
    await check_and_increment(
        redis=redis_client, scope="scope-B", identifier="user-1",
        max_count=3, window_seconds=60,
    )

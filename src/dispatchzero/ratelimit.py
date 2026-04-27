"""Redis-backed fixed-window rate limiter.

Same pattern as the /auth/login limiter from Phase 2, generalized so we can
apply it to /missions/request, /missions/generate, and /auth/signup.

Window strategy: fixed bucket aligned to wall-clock seconds. Each unique
(scope, identifier) gets its own counter that resets every `window_seconds`.
Trade-off: a caller can do up to `2 * max_count` in any rolling 2*window
period if they straddle the boundary. Acceptable for our caps (10s of calls,
not 1000s).

Atomic via INCR (returns post-increment count) + EXPIRE (idempotent — only
sets TTL if not already set).
"""
import time

import redis.asyncio as aioredis


class RateLimitExceeded(RuntimeError):
    """Raised when the caller has exhausted their bucket. Carries retry_after."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded; retry in {retry_after_seconds}s")


async def check_and_increment(
    *,
    redis: aioredis.Redis,
    scope: str,
    identifier: str,
    max_count: int,
    window_seconds: int,
) -> None:
    """Atomically increment the bucket counter; raise if over the cap.

    `scope` is a short label like 'mission_request' or 'signup_ip'.
    `identifier` is the caller fingerprint — user id, IP, etc.
    """
    now = int(time.time())
    bucket = now // window_seconds
    key = f"rl:{scope}:{identifier}:{bucket}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

    count = int(results[0])
    if count > max_count:
        retry_after = window_seconds - (now % window_seconds)
        raise RateLimitExceeded(retry_after_seconds=max(retry_after, 1))

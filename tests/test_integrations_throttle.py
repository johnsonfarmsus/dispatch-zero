import asyncio
import time

import pytest

from dispatchzero.integrations._throttle import MinIntervalThrottle


@pytest.mark.asyncio
async def test_throttle_does_not_delay_first_call():
    t = MinIntervalThrottle(min_interval_seconds=1.0)
    start = time.monotonic()
    async with t:
        pass
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_throttle_enforces_gap_between_calls():
    t = MinIntervalThrottle(min_interval_seconds=0.5)
    async with t:
        pass
    start = time.monotonic()
    async with t:
        pass
    elapsed = time.monotonic() - start
    assert 0.45 <= elapsed <= 0.7  # ~0.5s gap with some scheduler slop


@pytest.mark.asyncio
async def test_throttle_serializes_concurrent_calls():
    t = MinIntervalThrottle(min_interval_seconds=0.3)

    async def call():
        async with t:
            return time.monotonic()

    starts = await asyncio.gather(call(), call(), call())
    starts.sort()
    assert starts[1] - starts[0] >= 0.28
    assert starts[2] - starts[1] >= 0.28

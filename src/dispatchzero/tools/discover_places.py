"""One-shot CLI for manual place discovery debugging.

Usage (inside the app container on VPS 2):
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app \\
        python -m dispatchzero.tools.discover_places \\
        --callsign smoketest --lat 47.6605 --lng -117.4198 --radius-m 1500
"""
import argparse
import asyncio

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from dispatchzero.config import get_settings
from dispatchzero.db import get_engine
from dispatchzero.models import User
from dispatchzero.services.discovery import discover_nearby


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--callsign", required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with SessionLocal() as db:
        user = (
            await db.execute(
                select(User).where(User.callsign_lower == args.callsign.lower())
            )
        ).scalar_one_or_none()
        if user is None:
            print(f"no user with callsign {args.callsign!r}")
            return
        results = await discover_nearby(
            db=db, redis=redis, user=user,
            lat=args.lat, lng=args.lng, radius_m=args.radius_m, limit=args.limit,
        )

    for r in results:
        print(f"{r['category']:10s} {(r['name'] or '<unnamed>')!r:40s} osm:{r['osm_type']}/{r['osm_id']}")
    print(f"\n{len(results)} places")
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(_main())

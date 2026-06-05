"""Promote / demote a user's admin flag.

Designed to be the only way is_admin gets flipped on, so the trust root for
the admin surface stays "shell access to VPS 2." There's no /signup path
that creates an admin, no env var bootstrap, no admin-self-promotion route.

Run inside the app container:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app \\
        python -m dispatchzero.tools.user_admin promote <callsign>

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app \\
        python -m dispatchzero.tools.user_admin demote <callsign>

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app \\
        python -m dispatchzero.tools.user_admin list

Callsign matching is case-insensitive (uses callsign_lower). Idempotent —
promoting an already-admin user is a no-op, same for demoting.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from dispatchzero.db import get_engine
from dispatchzero.models import User


async def _set_admin(callsign: str, value: bool) -> int:
    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as db:
        user = (
            await db.execute(
                select(User).where(User.callsign_lower == callsign.lower())
            )
        ).scalar_one_or_none()
        if user is None:
            print(f"callsign {callsign!r} not found", file=sys.stderr)
            return 2
        if user.is_admin == value:
            verb = "already admin" if value else "already non-admin"
            print(f"{user.callsign}: {verb} (no change)")
            return 0
        user.is_admin = value
        await db.commit()
        print(f"{user.callsign}: is_admin -> {value}")
        return 0


async def _list_admins() -> int:
    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(User).where(User.is_admin.is_(True)).order_by(User.callsign)
            )
        ).scalars().all()
        if not rows:
            print("No admin users.")
            return 0
        print(f"{len(rows)} admin user(s):")
        for u in rows:
            print(f"  - {u.callsign}  ({u.adventure_style})")
        return 0


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_promote = sub.add_parser("promote", help="set is_admin=true")
    p_promote.add_argument("callsign")
    p_demote = sub.add_parser("demote", help="set is_admin=false")
    p_demote.add_argument("callsign")
    sub.add_parser("list", help="list all admin users")
    args = parser.parse_args()

    if args.cmd == "promote":
        return await _set_admin(args.callsign, True)
    if args.cmd == "demote":
        return await _set_admin(args.callsign, False)
    if args.cmd == "list":
        return await _list_admins()
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))

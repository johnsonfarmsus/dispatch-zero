"""Break-glass maintainer CLI for the community-submission review queue.

The PRIMARY review path is the in-app admin queue (dispatchzero.admin.routes,
the "Admin" link in Settings). This CLI is a server-side fallback for review
without the UI — handy over SSH, or if the frontend is down. It does NOT do
OSM publishing; use the web admin queue for the Submit-to-OSM flow.

Run inside the app container so settings + DB connection resolve normally:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app \\
        python -m dispatchzero.tools.review_submissions --reviewer <callsign>

For each pending submission, prints the metadata + a local path to the
photo. Then prompts:

    [a] approve   [r] reject (RETURNED)   [s] skip   [q] quit

Approve flips the Place to ACTIVE and re-stamps the contribution card
VERIFIED; reject re-stamps RETURNED (and deletes the orphan Place — see
services.submissions.reject_submission). The submitter's dossier card
updates in place — no separate notification stream.

Designed for "you, on Sunday evening, with a coffee" — not a high-volume
moderation tool. Re-run it occasionally; it skips already-reviewed rows
because the query filters status='pending'.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from dispatchzero.db import get_engine
from dispatchzero.models import (
    Place,
    Submission,
    SubmissionStatus,
    User,
)
from dispatchzero.services.submissions import (
    SubmissionNotFoundError,
    approve_submission,
    reject_submission,
)


async def _review_one(
    db, reviewer: User, submission: Submission, place: Place, submitter: User,
) -> str:
    """Print the submission's details + prompt the maintainer.

    Returns one of: 'approved', 'rejected', 'skipped', 'quit'.
    """
    print()
    print("=" * 72)
    print(f"  PLACE:        {place.name!r}  ({place.category})")
    print(f"  SUBMITTER:    {submitter.callsign}  ({submitter.adventure_style})")
    print(f"  DESCRIPTION:  {submission.description or '(none)'}")
    print(f"  SUBMITTED:    {submission.submitted_at.isoformat()}")
    print(f"  PHOTO PATH:   {submission.photo_url}")
    print(f"  CARD PATH:    {submission.card_path}")
    print(f"  ID:           {submission.id}")
    print()
    print("  [a] approve   [r] reject   [s] skip   [q] quit")
    choice = input("  > ").strip().lower()
    if choice in ("a", "approve"):
        await approve_submission(db=db, reviewer=reviewer, submission_id=submission.id)
        print("  → APPROVED. Place is now ACTIVE; card re-stamped VERIFIED.")
        return "approved"
    if choice in ("r", "reject"):
        await reject_submission(db=db, reviewer=reviewer, submission_id=submission.id)
        print("  → RETURNED. Place stays PENDING; card re-stamped RETURNED.")
        return "rejected"
    if choice in ("q", "quit"):
        print("  → quitting (no further submissions reviewed).")
        return "quit"
    print("  → skipped (status unchanged).")
    return "skipped"


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Callsign of the user to record as the reviewer (typically you).",
    )
    args = parser.parse_args()

    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        reviewer = (
            await db.execute(
                select(User).where(User.callsign_lower == args.reviewer.lower())
            )
        ).scalar_one_or_none()
        if reviewer is None:
            print(f"reviewer callsign {args.reviewer!r} not found", file=sys.stderr)
            return 2

        rows = (
            await db.execute(
                select(Submission, Place, User)
                .join(Place, Place.id == Submission.place_id)
                .join(User, User.id == Submission.user_id)
                .where(Submission.status == SubmissionStatus.PENDING.value)
                .order_by(Submission.submitted_at.asc())
            )
        ).all()

        if not rows:
            print("No pending submissions. Clean queue.")
            return 0

        print(f"{len(rows)} pending submission(s) to review.")
        counts = {"approved": 0, "rejected": 0, "skipped": 0}
        for submission, place, submitter in rows:
            try:
                outcome = await _review_one(db, reviewer, submission, place, submitter)
            except SubmissionNotFoundError as e:
                print(f"  ! {e}; skipping")
                outcome = "skipped"
            if outcome == "quit":
                break
            counts[outcome] = counts.get(outcome, 0) + 1

        print()
        print(f"Session done. approved={counts['approved']}  rejected={counts['rejected']}  skipped={counts['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))

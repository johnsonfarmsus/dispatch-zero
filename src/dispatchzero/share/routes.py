"""Public share routes — `/c/{share_token}` HTML page + card image.

Unauthenticated. Returns a minimal HTML page (card image, place name, date)
plus OpenGraph tags so link unfurls embed the card. The matching JPEG is
served at `/c/{share_token}/card.jpg` from the same on-disk file used by
the authed Debrief endpoint.

Privacy posture: the token is unguessable (~56 bits); coordinates are
never exposed; the user's callsign is on the card image itself by
their own choice when they share. No DB lookup leaks user-identifying
information beyond what the user already chose to put on the card.
"""
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from dispatchzero.config import get_settings
from dispatchzero.db import get_session
from dispatchzero.models import Completion, Mission, Place, Submission
from dispatchzero.services.cards import compose_mission_card

router = APIRouter(prefix="/c", tags=["share"])


async def _load_completion_by_token(
    db: AsyncSession, share_token: str
) -> tuple[Completion, Mission, Place] | None:
    """Returns the completion + mission + place if the token matches a
    completion, or None if no completion has this token. (Caller falls
    through to submissions before deciding to 404.)"""
    completion = (
        await db.execute(
            select(Completion).where(Completion.share_token == share_token)
        )
    ).scalar_one_or_none()
    if completion is None:
        return None
    mission = (
        await db.execute(select(Mission).where(Mission.id == completion.mission_id))
    ).scalar_one()
    place = (
        await db.execute(select(Place).where(Place.id == completion.place_id))
    ).scalar_one()
    return completion, mission, place


async def _load_submission_by_token(
    db: AsyncSession, share_token: str
) -> tuple[Submission, Place | None] | None:
    """Returns the submission + its place if the token matches, or
    (submission, None) if the submission exists but its Place row has
    been hard-deleted (Returned submissions garbage-collect their orphan
    Place — see services.submissions.reject_submission). Caller falls
    back to submission.place_name_snapshot for display in that case.

    Returns None only when the token doesn't match any submission at all."""
    submission = (
        await db.execute(
            select(Submission).where(Submission.share_token == share_token)
        )
    ).scalar_one_or_none()
    if submission is None:
        return None
    place: Place | None = None
    if submission.place_id is not None:
        place = (
            await db.execute(select(Place).where(Place.id == submission.place_id))
        ).scalar_one_or_none()
    return submission, place


def _absolute_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


_SUBMISSION_BLURB = {
    "pending": "A contribution was submitted at {name}, awaiting verification.",
    "approved": "A contribution at {name} was verified into the registry.",
    "returned": "A contribution was submitted at {name}.",
}


@router.get("/{share_token}", response_class=HTMLResponse)
async def share_page(
    share_token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Public share page for either a mission completion OR a community
    submission. Both use the /c/{token} URL prefix (set by the respective
    "Copy Share Link" buttons in the dossier), so this route looks up
    completion first and falls back to submission before returning 404."""
    description: str
    completion_result = await _load_completion_by_token(db, share_token)
    if completion_result is not None:
        _completion, _mission, place = completion_result
        place_name = place.name or "Unmarked target"
        description = f"A dispatch was completed at {place_name}."
    else:
        submission_result = await _load_submission_by_token(db, share_token)
        if submission_result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        submission, place = submission_result
        # Place may be None for Returned submissions (orphan place was
        # deleted at return time). Snapshot kept on the submission row
        # carries the name forward.
        place_name = (
            (place.name if place is not None else None)
            or submission.place_name_snapshot
            or "Unmarked target"
        )
        blurb_template = _SUBMISSION_BLURB.get(
            submission.status, _SUBMISSION_BLURB["pending"]
        )
        description = blurb_template.format(name=place_name)

    card_url = _absolute_url(request, f"/c/{share_token}/card.jpg")
    page_url = _absolute_url(request, f"/c/{share_token}")
    title = escape(f"{place_name} / Dispatch Zero")
    description = escape(description)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{card_url}">
<meta property="og:url" content="{page_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{card_url}">
<style>
  :root {{
    --bg: #0e0c0a;
    --text: #e8e1d8;
    --text-muted: #857d72;
    --rule: #2a2520;
  }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem 1rem;
  }}
  .card-wrap {{
    width: 100%;
    max-width: 480px;
  }}
  .card-wrap img {{
    width: 100%;
    height: auto;
    display: block;
    border: 1px solid var(--rule);
  }}
  .cta {{
    margin-top: 2rem;
    text-align: center;
  }}
  .cta-line {{
    color: var(--text);
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 1rem;
    letter-spacing: 0.04em;
    margin: 0;
  }}
  .cta-link {{
    display: inline-block;
    margin-top: 0.5rem;
    color: #f4d35e;
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.9rem;
    letter-spacing: 0.04em;
    text-decoration: none;
    border: 1px solid #3a2a0a;
    padding: 0.5rem 1rem;
    border-radius: 4px;
  }}
  .cta-link:hover {{
    background: #3a2a0a;
  }}
  footer {{
    margin-top: 2.5rem;
    color: var(--text-muted);
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
  }}
  footer a {{ color: var(--text-muted); text-decoration: none; }}
</style>
</head>
<body>
  <div class="card-wrap"><img src="{card_url}" alt="Mission card"></div>
  <div class="cta">
    <p class="cta-line">Receive your own dispatch.</p>
    <a class="cta-link" href="/">dispatchzero.ataary.com →</a>
  </div>
  <footer>
    <a href="/">// dispatch zero //</a>
  </footer>
</body>
</html>
"""
    return HTMLResponse(content=html)


@router.get("/{share_token}/card.jpg")
async def share_card(
    share_token: str,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Public card image. Handles both completion cards (regenerated on miss
    from the photo) and submission cards (served as-is from disk; the
    submission service generates them at create/approve/reject time)."""
    settings = get_settings()

    completion_result = await _load_completion_by_token(db, share_token)
    if completion_result is not None:
        completion, mission, place = completion_result
        card_path = Path(settings.photo_upload_dir) / "cards" / f"{completion.id}.jpg"

        if not card_path.exists():
            # Regenerate on miss so the public URL never 404s due to a stale
            # capture without a card file.
            photo_path = Path(completion.photo_url) if completion.photo_url else None
            if photo_path is None or not photo_path.exists():
                raise HTTPException(status.HTTP_404_NOT_FOUND, "image missing")
            from dispatchzero.models import User
            from dispatchzero.services.rank import (
                completions_to_rank, stats_at_completion,
            )

            user = (
                await db.execute(select(User).where(User.id == completion.user_id))
            ).scalar_one()
            total_then, week_then = await stats_at_completion(
                db, user_id=completion.user_id,
                at_time=completion.completed_at, include_self=True,
            )
            rank_then = completions_to_rank(total_then)
            try:
                compose_mission_card(
                    photo_path=photo_path,
                    place_name=place.name or "Unmarked target",
                    callsign=user.callsign,
                    completed_at=completion.completed_at,
                    adventure_style=mission.adventure_style,
                    rank_at_completion=rank_then,
                    completions_total=total_then,
                    completions_this_week=week_then,
                    dispatch_summary=mission.dispatch_summary,
                    output_path=card_path,
                )
            except Exception as e:  # noqa: BLE001
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "card unavailable"
                ) from e

        return FileResponse(card_path, media_type="image/jpeg")

    submission_result = await _load_submission_by_token(db, share_token)
    if submission_result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    submission, _place = submission_result

    # Prefer the path the service recorded. Fall back to the conventional
    # location if the column is blank (older rows from before card_path was
    # being set, or a failed compose).
    card_path = (
        Path(submission.card_path)
        if submission.card_path
        else Path(settings.photo_upload_dir) / "submission_cards" / f"{submission.id}.jpg"
    )
    if not card_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "image missing")
    return FileResponse(card_path, media_type="image/jpeg")

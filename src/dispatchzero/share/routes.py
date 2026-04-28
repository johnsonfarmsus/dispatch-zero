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
from dispatchzero.models import Completion, Mission, Place
from dispatchzero.services.cards import compose_mission_card

router = APIRouter(prefix="/c", tags=["share"])


async def _load_completion_by_token(
    db: AsyncSession, share_token: str
) -> tuple[Completion, Mission, Place]:
    completion = (
        await db.execute(
            select(Completion).where(Completion.share_token == share_token)
        )
    ).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    mission = (
        await db.execute(select(Mission).where(Mission.id == completion.mission_id))
    ).scalar_one()
    place = (
        await db.execute(select(Place).where(Place.id == completion.place_id))
    ).scalar_one()
    return completion, mission, place


def _absolute_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


@router.get("/{share_token}", response_class=HTMLResponse)
async def share_page(
    share_token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    completion, _mission, place = await _load_completion_by_token(db, share_token)
    place_name = place.name or "Unmarked target"
    date_str = completion.completed_at.strftime("%B %-d, %Y")
    card_url = _absolute_url(request, f"/c/{share_token}/card.jpg")
    page_url = _absolute_url(request, f"/c/{share_token}")

    # Minimal page. The card image carries the visual story; the page is
    # essentially a frame for the unfurl preview.
    title = escape(f"{place_name} — Dispatch Zero")
    description = escape(f"A dispatch was completed at {place_name}.")
    safe_place = escape(place_name)
    safe_date = escape(date_str)

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
  .meta {{
    margin-top: 1rem;
    text-align: center;
  }}
  .place {{
    font-size: 1.25rem;
    margin: 0;
  }}
  .date {{
    color: var(--text-muted);
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.85rem;
    margin: 0.25rem 0 0;
  }}
  footer {{
    margin-top: 2rem;
    color: var(--text-muted);
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
  }}
  footer a {{ color: var(--text-muted); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="card-wrap"><img src="{card_url}" alt="Mission card"></div>
  <div class="meta">
    <p class="place">{safe_place}</p>
    <p class="date">{safe_date}</p>
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
    """Public card image. Same on-disk file as the authed Debrief endpoint."""
    completion, mission, place = await _load_completion_by_token(db, share_token)
    settings = get_settings()
    card_path = Path(settings.photo_upload_dir) / "cards" / f"{completion.id}.jpg"

    if not card_path.exists():
        # Regenerate on miss so the public URL never 404s due to a stale
        # capture without a card file.
        photo_path = Path(completion.photo_url) if completion.photo_url else None
        if photo_path is None or not photo_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "image missing")
        # We need the user for the callsign on the card; load it.
        from dispatchzero.models import User

        user = (
            await db.execute(select(User).where(User.id == completion.user_id))
        ).scalar_one()
        try:
            compose_mission_card(
                photo_path=photo_path,
                place_name=place.name or "Unmarked target",
                callsign=user.callsign,
                completed_at=completion.completed_at,
                adventure_style=mission.adventure_style,
                output_path=card_path,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "card unavailable"
            ) from e

    return FileResponse(card_path, media_type="image/jpeg")

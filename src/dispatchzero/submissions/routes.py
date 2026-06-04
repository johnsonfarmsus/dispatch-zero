"""POST /submissions/capture + GET endpoints for a submitter's own card/photo.

Submission lifecycle is:
- POST /submissions/capture          create + persist photo + compose PENDING card
- GET  /submissions/{id}             read the submission (self only)
- GET  /submissions/{id}/photo.jpg   raw thumbnail (self only)
- GET  /submissions/{id}/card.jpg    composed contribution card (self only)

Approval/rejection live in services.submissions and are driven from the
admin CLI (dispatchzero.tools.review_submissions) rather than HTTP — keeping
moderator actions off the public API surface.
"""
import logging
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.db import get_session
from dispatchzero.models import Place, PlaceCategory, Submission, User
from dispatchzero.services.submissions import (
    SubmissionNotFoundError,
    SubmissionRejectedError,
    create_submission,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["submissions"])


class SubmissionOut(BaseModel):
    id: uuid.UUID
    place_id: uuid.UUID
    status: str
    description: str | None
    share_token: str
    submitted_at: str  # ISO 8601


class SubmissionListItem(BaseModel):
    """Slimmer payload for dossier-list rendering. Mirrors CompletionListItem
    so the frontend can stack both into one list ordered by date."""
    id: uuid.UUID
    place_id: uuid.UUID
    place_name: str | None
    place_category: str
    description: str | None
    status: str
    share_token: str
    submitted_at: str  # ISO 8601


def _submission_to_out(s: Submission) -> SubmissionOut:
    return SubmissionOut(
        id=s.id,
        place_id=s.place_id,
        status=s.status,
        description=s.description,
        share_token=s.share_token,
        submitted_at=s.submitted_at.isoformat(),
    )


_CATEGORY_VALUES = Literal[
    "mural", "sculpture", "memorial", "historic", "viewpoint",
    "church", "park", "infrastructure", "civic",
]


@router.post("/capture", response_model=SubmissionOut)
async def capture(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    photo: Annotated[UploadFile, File(description="Captured photo")],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    category: Annotated[_CATEGORY_VALUES, Form()],
    lat: Annotated[float, Form(ge=-90.0, le=90.0)],
    lng: Annotated[float, Form(ge=-180.0, le=180.0)],
    description: Annotated[str | None, Form(max_length=140)] = None,
) -> SubmissionOut:
    """Submit a community POI.

    Coordinates come from the browser (navigator.geolocation), not from
    the photo's EXIF — most users don't enable Location for the iOS
    Camera app, but the browser can request its own location permission
    independently. The photo's EXIF DateTimeOriginal still has to be
    within the freshness window (anti-camera-roll).

    Returns the new Submission row immediately, status=pending. The user can
    fetch the composed contribution card at GET /submissions/{id}/card.jpg.
    """
    raw = await photo.read()
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "photo upload is empty",
        )
    try:
        submission = await create_submission(
            db=db, user=user,
            raw_photo=raw,
            name=name,
            category=PlaceCategory(category),
            description=description,
            lat=lat,
            lng=lng,
        )
    except SubmissionRejectedError as e:
        # 422 to mirror the mission-capture failure shape — the upload
        # passed structural validation but failed semantic checks
        # (EXIF, freshness, content).
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _submission_to_out(submission)


@router.get("", response_model=list[SubmissionListItem])
async def list_submissions(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[SubmissionListItem]:
    """The current user's submissions, newest first. The dossier screen
    fetches this alongside /missions/completions and merges the two lists
    by date so the user sees one unified history."""
    rows = (
        await db.execute(
            select(Submission, Place)
            .join(Place, Place.id == Submission.place_id)
            .where(Submission.user_id == user.id)
            .order_by(Submission.submitted_at.desc())
            .limit(50)
        )
    ).all()
    return [
        SubmissionListItem(
            id=s.id,
            place_id=p.id,
            place_name=p.name,
            place_category=p.category,
            description=s.description,
            status=s.status,
            share_token=s.share_token,
            submitted_at=s.submitted_at.isoformat(),
        )
        for s, p in rows
    ]


@router.get("/{submission_id}", response_model=SubmissionOut)
async def get_submission(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionOut:
    submission = await _load_self(db, submission_id, user)
    return _submission_to_out(submission)


@router.get("/{submission_id}/photo.jpg")
async def submission_photo(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    submission = await _load_self(db, submission_id, user)
    if not submission.photo_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    photo_path = Path(submission.photo_url)
    if not photo_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    return FileResponse(photo_path, media_type="image/jpeg")


@router.get("/{submission_id}/card.jpg")
async def submission_card(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Composed contribution card. Status stamp tracks the workflow (PENDING /
    VERIFIED / RETURNED). The route doesn't regenerate — that happens in
    services.submissions when status changes."""
    submission = await _load_self(db, submission_id, user)
    if not submission.card_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "card missing")
    card_path = Path(submission.card_path)
    if not card_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "card missing")
    return FileResponse(card_path, media_type="image/jpeg")


async def _load_self(
    db: AsyncSession, submission_id: uuid.UUID, user: User,
) -> Submission:
    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    if submission.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your submission")
    return submission

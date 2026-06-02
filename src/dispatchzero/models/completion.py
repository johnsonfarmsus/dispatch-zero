import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class LocationReason(StrEnum):
    """Why a user gave a place a 👎.

    Collapsed from a previous 4-value enum (gone / not_found / inaccessible /
    unsafe) — for routing purposes the only distinction that matters is
    "stop sending people here" vs "user couldn't find it":

    - UNREACHABLE: gone, demolished, fenced off, dangerous — same answer:
      retire / flag the place. Migration 0009 backfilled gone+inaccessible+
      unsafe → unreachable.
    - NOT_FOUND: user couldn't locate it (wrong coords, no signage, missed it
      in the dark). Could be the user's miss OR a coordinate problem — needs
      more reports before action.
    """
    UNREACHABLE = "unreachable"
    NOT_FOUND = "not_found"


class MissionReason(StrEnum):
    BLAND = "bland"
    INACCURATE = "inaccurate"
    WRONG_TONE = "wrong_tone"
    CONFUSING = "confusing"


class Completion(Base):
    __tablename__ = "completions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )

    photo_url: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # Verification *outcome* is persisted; the inputs (capture lat/lng/accuracy
    # and EXIF metadata) are used live in verify_capture and discarded.
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    location_rating: Mapped[str | None] = mapped_column(String(8), nullable=True)
    mission_rating: Mapped[str | None] = mapped_column(String(8), nullable=True)
    location_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mission_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Unguessable short token used in the public share URL `/c/{share_token}`.
    # Generated on insert (see services.mission_flow.capture_mission).
    share_token: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)

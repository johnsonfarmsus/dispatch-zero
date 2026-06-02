"""Per-user permanent exclusions of specific places.

Distinct from UserPlaceHistory (which records *completed* visits and feeds
the 30-day re-entry filter). An exclusion is a user saying "don't dispatch
me to this place again, ever" — the canonical use case being "I went to
check and it doesn't exist / is inaccessible / has been demolished."

The same signal also contributes to the global auto-flag rule in
mission_flow._apply_auto_retire: if multiple distinct users exclude the
same place, the place gets flagged for the maintainer to review.

Reports are created via POST /places/{id}/report — no GPS-proximity check
required (local knowledge is the point; you might know a building is gone
without standing next to it).
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class ExclusionReason(StrEnum):
    """Why the user excluded this place. Same vocabulary as Completion.location_reason
    so the global auto-flag logic can treat both signals uniformly."""
    UNREACHABLE = "unreachable"
    NOT_FOUND = "not_found"


class UserPlaceExclusion(Base):
    __tablename__ = "user_place_exclusions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # One exclusion per (user, place) — re-reporting is idempotent (upsert
        # in the service updates the reason).
        UniqueConstraint("user_id", "place_id", name="uq_user_place_exclusion"),
    )

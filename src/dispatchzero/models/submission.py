"""Community submissions — user-reported points of interest.

When a user reports a POI via POST /submissions/capture, two rows land:
- A Place row with osm_type='community', status='pending', submitted_by_user_id
  set so the user gets repeat-visit framing if they're later dispatched there.
- A Submission row pointing at that Place, holding the review workflow state
  (status, reviewer, photo path, composed contribution card path).

The Place is the "what" (a point in space with a name and category). The
Submission is the "how this got here" (who submitted, when, what they said,
what the reviewer decided). They're 1:1 but separated so a Place can outlive
the submission flow once approved — it becomes just another row in the
dispatch pool.

Approval lifecycle:
    PENDING  → APPROVED  (place flips to ACTIVE, joins dispatch pool, user gets
                          a rank point, contribution card re-stamped VERIFIED)
    PENDING  → RETURNED  (place stays PENDING, contribution card re-stamped
                          RETURNED, no rank point)

The submitter sees the card in their dossier immediately on submit (stamped
PENDING). The card's status restamp on approval/rejection is the only
notification — there's no separate notification stream. The user's stat line
shows pending count alongside their completion count so they can see the
review is in flight.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class SubmissionStatus(StrEnum):
    """Review state of a community submission. See module docstring for lifecycle."""
    PENDING = "pending"
    APPROVED = "approved"
    RETURNED = "returned"


class Submission(Base):
    __tablename__ = "submissions"

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

    # Filesystem path to the saved (EXIF-stripped) submission photo. Lives
    # under /uploads/submissions/{user_id}/{submission_id}.jpg. Same lifecycle
    # rules as completion.photo_url — protected from the rsync wipe by
    # deploy/*.sh's --exclude 'uploads' (now enforced by .githooks/pre-commit).
    photo_url: Mapped[str] = mapped_column(String(400), nullable=False)

    # User-typed description, max 140 chars. Optional but encouraged — gives
    # the reviewer context and feeds the briefing prompt later.
    description: Mapped[str | None] = mapped_column(String(140), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )

    # Composed "contribution card" (4:5 JPEG, status-stamped). Path follows
    # /uploads/submission_cards/{submission_id}.jpg. Regenerated when status
    # changes so the PENDING → VERIFIED / RETURNED stamp tracks the workflow.
    card_path: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # Unguessable share token (same shape as Completion.share_token) so the
    # /c/{token} share URL works for contribution cards too.
    share_token: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Set when the reviewer acts. reviewer_user_id is nullable because the
    # reviewer might no longer exist (deleted account) by the time we look.
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

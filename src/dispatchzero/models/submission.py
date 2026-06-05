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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Nullable + SET NULL on delete: when a reviewer Returns a submission,
    # the linked Place is hard-deleted (it would only sit in the places
    # table as orphan clutter, status=pending and forever excluded from
    # dispatch). place_id becomes NULL on the surviving Submission row so
    # the user's dossier history still reads the submission card. See
    # services.submissions.reject_submission + migration 0015.
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Filesystem path to the saved (EXIF-stripped) submission photo. Lives
    # under /uploads/submissions/{user_id}/{submission_id}.jpg. Same lifecycle
    # rules as completion.photo_url — protected from the rsync wipe by
    # deploy/*.sh's --exclude 'uploads' (now enforced by .githooks/pre-commit).
    photo_url: Mapped[str] = mapped_column(String(400), nullable=False)

    # User-typed description, max 140 chars. Optional but encouraged — gives
    # the reviewer context and feeds the briefing prompt later.
    description: Mapped[str | None] = mapped_column(String(140), nullable=True)

    # Optional URL the submitter provides (Wikipedia article, official site,
    # local history page, etc.). On OSM publish:
    #   - wikipedia.org URLs → derive wikipedia=<lang>:<title> tag
    #   - other URLs → website=<url> tag
    # Surfaced to the admin as a clickable line on the review-queue card so
    # they can verify the place before approving.
    external_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

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

    # Optional reviewer-attached note shown on the submitter's dossier card
    # when the submission is RETURNED. Surfaces "why" so the submitter isn't
    # left guessing — used at the reviewer's discretion; blank when there's
    # nothing useful to add.
    review_note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Captured at the moment of Return (or at any future point where the
    # linked Place gets deleted out from under us). Lets the dossier list
    # render "Combine Mural" even after the orphan Place row has been
    # nuked. Pending + Approved submissions always read the live place.name;
    # only Returned submissions consult this snapshot.
    place_name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # OSM pre-flight check results. Populated by a background task fired
    # after the submission row commits — we query OSM for matching POIs
    # within ~50m and store what we found. ADVISORY ONLY: surfaced on the
    # admin review card so the reviewer knows whether the area is dense
    # with similar OSM nodes before approving / submitting to OSM. Does
    # not gate any action. See services.osm_preflight + migration 0019.
    osm_preflight_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # JSONB array of nearby matches, each {name, osm_type, osm_id, osm_url,
    # distance_m, tags_summary}. Empty array means "ran, found none."
    osm_preflight_matches: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )

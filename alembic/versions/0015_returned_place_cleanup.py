"""returned submissions: allow Place cleanup without losing the Submission row

When a reviewer Returns a submission, the linked Place is dead weight —
status=PENDING means it's excluded from dispatch, but the row sits in the
places table as orphan clutter. This migration lets reject_submission
hard-delete the Place while preserving the Submission as a dossier record:

- submissions.place_id: now nullable + ON DELETE SET NULL (was non-null +
  CASCADE, which would have deleted the Submission too).
- submissions.place_name_snapshot: short copy of the place's name at the
  moment of return. The dossier list reads place_name_snapshot when
  place_id is NULL so the user's history still shows something meaningful
  ("Combine Mural — RETURNED") rather than "(deleted)".

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("place_name_snapshot", sa.String(length=200), nullable=True),
    )
    # Swap the FK from CASCADE to SET NULL so deleting a Place leaves the
    # Submission row alive with place_id=NULL.
    op.drop_constraint("submissions_place_id_fkey", "submissions", type_="foreignkey")
    op.alter_column("submissions", "place_id", nullable=True)
    op.create_foreign_key(
        "submissions_place_id_fkey",
        "submissions",
        "places",
        ["place_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # NOTE: rolling back when there are submissions with place_id=NULL
    # would fail the NOT NULL constraint. The downgrade only works on a
    # clean DB. Acceptable for a forward-only deployment.
    op.drop_constraint("submissions_place_id_fkey", "submissions", type_="foreignkey")
    op.alter_column("submissions", "place_id", nullable=False)
    op.create_foreign_key(
        "submissions_place_id_fkey",
        "submissions",
        "places",
        ["place_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("submissions", "place_name_snapshot")

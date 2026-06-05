"""osm skip-decision tracking on places

When a place comes up as a completion-driven OSM-publish candidate (a user
finished a mission at a Wikipedia / GNIS / internal place) and the reviewer
decides NOT to push it upstream, we want to remember that decision so the
candidate doesn't keep reappearing in the queue every time someone else
completes the same place.

Two columns on places, both NULL by default:

- osm_skipped_at         when the reviewer hit Skip
- osm_skipped_by_user_id which admin made the call (audit)

A non-NULL osm_skipped_at means "don't surface this place as a candidate
ever again." It does NOT prevent a future admin from manually un-skipping
via DB if needed; the queue query just filters it out.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "places",
        sa.Column("osm_skipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("osm_skipped_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "places_osm_skipped_by_fkey",
        "places",
        "users",
        ["osm_skipped_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "places_osm_skipped_by_fkey", "places", type_="foreignkey"
    )
    op.drop_column("places", "osm_skipped_by_user_id")
    op.drop_column("places", "osm_skipped_at")

"""submission OSM pre-flight check

Two columns on submissions, populated by a background task fired
after /submissions/capture commits:

- osm_preflight_checked_at  when the Overpass round-trip finished.
                            NULL means the check hasn't run yet
                            (or failed silently — see service for
                            the error-handling posture).

- osm_preflight_matches     JSONB array of nearby OSM matches at
                            the submitted category. Each element is
                            {name, osm_type, osm_id, osm_url,
                             distance_m, tags_summary}. Empty array
                            means "ran, found nothing." Non-empty
                            array surfaces as a list on the admin
                            review card so the reviewer can verify.

The pre-flight is ADVISORY, not gating: Submit-to-OSM still works
regardless of the result. The point is to give the admin a heads-up
that an existing OSM node may overlap before they manually verify
via the OSM map link.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column(
            "osm_preflight_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "submissions",
        sa.Column("osm_preflight_matches", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "osm_preflight_matches")
    op.drop_column("submissions", "osm_preflight_checked_at")

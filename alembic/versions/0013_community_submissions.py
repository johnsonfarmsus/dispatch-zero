"""community submissions: place fields + submissions table

Adds the data model behind user-reported POIs. See
src/dispatchzero/models/submission.py for the workflow.

Place gets two new columns:
- submitted_by_user_id  — non-null when the place came in via the submission
  flow. Lets _user_has_visited treat the submission as a first visit so a
  future dispatch to the same place gets repeat-visit briefing framing.
- submission_description — the 140-char user blurb. Feeds the briefing prompt
  as flavor when set.

New submissions table holds the review workflow state (status + reviewer +
photo + composed contribution card path).

A sequence backs osm_id allocation for osm_type='community' so the Place
table's (osm_type, osm_id) uniqueness keeps working without colliding with
OSM-assigned numeric IDs (which can reach ~12B).

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-03
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Place: widen osm_type from VARCHAR(8) to VARCHAR(16) so we can use the
    # longer "community" tag (and future import-source identifiers) without
    # truncation. The 8-char ceiling was sized for OSM's own types and didn't
    # leave room for source-tagging additions.
    op.execute(
        "ALTER TABLE places ALTER COLUMN osm_type TYPE VARCHAR(16)"
    )

    # Place: add submitter attribution + the optional user description.
    op.execute(
        "ALTER TABLE places ADD COLUMN submitted_by_user_id UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE places ADD COLUMN submission_description VARCHAR(140)"
    )
    # Lookup speed for the _user_has_visited check (filter by submitted_by_user_id
    # is one half of the OR).
    op.execute(
        "CREATE INDEX ix_places_submitted_by_user "
        "ON places (submitted_by_user_id) "
        "WHERE submitted_by_user_id IS NOT NULL"
    )

    # Dedicated sequence for osm_id values when osm_type='community'. Keeps the
    # (osm_type, osm_id) uniqueness constraint working without picking IDs
    # that collide with OSM's own node IDs (those are positive bigints
    # allocated by api.openstreetmap.org).
    op.execute("CREATE SEQUENCE community_place_id_seq")

    op.execute("""
        CREATE TABLE submissions (
            id                UUID PRIMARY KEY,
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            place_id          UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            photo_url         VARCHAR(400) NOT NULL,
            description       VARCHAR(140),
            status            VARCHAR(16) NOT NULL DEFAULT 'pending',
            card_path         VARCHAR(400),
            share_token       VARCHAR(12) NOT NULL UNIQUE,
            submitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at       TIMESTAMPTZ,
            reviewer_user_id  UUID REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    # Two query patterns the route + admin tool exercise:
    op.execute(
        "CREATE INDEX ix_submissions_user_submitted_at "
        "ON submissions (user_id, submitted_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_submissions_status_submitted_at "
        "ON submissions (status, submitted_at) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS submissions")
    op.execute("DROP SEQUENCE IF EXISTS community_place_id_seq")
    op.execute("DROP INDEX IF EXISTS ix_places_submitted_by_user")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS submission_description")
    op.execute("ALTER TABLE places DROP COLUMN IF EXISTS submitted_by_user_id")

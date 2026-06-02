"""user_place_exclusions: per-user permanent place exclusions

A user reports that a place is gone / inaccessible / wrong. That place
never gets dispatched to that user again. Distinct from UserPlaceHistory
(which tracks completed visits and feeds the 30-day re-entry filter).

Multiple users' reports for the same place also feed the global auto-flag
rule — see services.mission_flow._apply_auto_retire.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-02
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_place_exclusions (
            id           UUID PRIMARY KEY,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            place_id     UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            reason       VARCHAR(16) NOT NULL,
            reported_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_place_exclusion UNIQUE (user_id, place_id)
        )
    """)
    # Discovery filter does WHERE user_id = $X — index helps that lookup.
    op.execute(
        "CREATE INDEX ix_user_place_exclusions_user ON user_place_exclusions (user_id)"
    )
    # Auto-flag rule counts distinct users per place — index helps THAT lookup too.
    op.execute(
        "CREATE INDEX ix_user_place_exclusions_place ON user_place_exclusions (place_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_place_exclusions")

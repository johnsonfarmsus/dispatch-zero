"""add completions table; drop unused xp/rank columns from users

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-26
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the completions table.
    op.execute("""
        CREATE TABLE completions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            photo_url VARCHAR(400),
            capture_lat DOUBLE PRECISION NOT NULL,
            capture_lng DOUBLE PRECISION NOT NULL,
            capture_accuracy_m DOUBLE PRECISION,
            had_exif BOOLEAN NOT NULL DEFAULT FALSE,
            exif_datetime_delta_seconds INTEGER,
            had_exif_gps BOOLEAN NOT NULL DEFAULT FALSE,
            verified BOOLEAN NOT NULL DEFAULT FALSE,
            location_rating VARCHAR(8),
            mission_rating VARCHAR(8),
            location_reason VARCHAR(16),
            completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_completions_user_completed ON completions (user_id, completed_at DESC)")
    op.execute("CREATE INDEX ix_completions_place ON completions (place_id, completed_at DESC)")
    op.execute("CREATE INDEX ix_completions_mission ON completions (mission_id, completed_at DESC)")

    # Drop unused xp/rank columns introduced in 0002 (decided to use completions count instead).
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS xp")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS rank")


def downgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN rank VARCHAR(32) NOT NULL DEFAULT 'recruit'")
    op.execute("DROP TABLE IF EXISTS completions")

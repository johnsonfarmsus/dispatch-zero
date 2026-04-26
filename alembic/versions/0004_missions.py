"""add missions and mission_stops tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE missions (
            id UUID PRIMARY KEY,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            adventure_style VARCHAR(16) NOT NULL,
            dispatch_summary VARCHAR(400) NOT NULL,
            briefing_text VARCHAR(2200) NOT NULL,
            clue VARCHAR(240),
            badge_framing VARCHAR(120),
            mission_thumbs_up INTEGER NOT NULL DEFAULT 0,
            mission_thumbs_down INTEGER NOT NULL DEFAULT 0,
            implicit_completions INTEGER NOT NULL DEFAULT 0,
            audio_url VARCHAR(400),
            ai_model VARCHAR(64),
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX ix_missions_place_style_status "
        "ON missions (place_id, adventure_style, status)"
    )
    op.execute("""
        CREATE TABLE mission_stops (
            id UUID PRIMARY KEY,
            mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            display_order INTEGER NOT NULL DEFAULT 0,
            required BOOLEAN NOT NULL DEFAULT TRUE,
            CONSTRAINT uq_mission_stop UNIQUE (mission_id, place_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mission_stops")
    op.execute("DROP TABLE IF EXISTS missions")

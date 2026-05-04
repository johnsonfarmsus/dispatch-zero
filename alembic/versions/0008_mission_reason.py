"""add mission_reason column to completions

Mirrors location_reason: a short tag the user can pick when downvoting
the mission text. Used to inform regen.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-03
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE completions ADD COLUMN mission_reason VARCHAR(16)")


def downgrade() -> None:
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS mission_reason")

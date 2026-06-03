"""missions.repeat_visit: flag follow-up briefings out of the shared library

When a user is dispatched to a place they've already visited, the briefing
is force-regenerated with follow-up framing ("secondary sweep", "ongoing
observation", "the file is reopened"). That framing wouldn't make sense to
a first-time visitor — so we mark these missions and exclude them from
library lookups for new users.

Default false: pre-existing missions are first-visit by definition.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-02
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE missions ADD COLUMN repeat_visit BOOLEAN "
        "NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE missions DROP COLUMN IF EXISTS repeat_visit")

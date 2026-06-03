"""missions.teaser: short in-voice line for the candidate-list UI

Stage 3 adds a list-of-candidates picker — when a user requests a dispatch,
the system returns N options each with a one-sentence teaser ("Where
packages hide more than postage." for the Harrington Post Office). The
teaser is stored on the Mission row, generated as part of the same OLMo
structured-output call that produces dispatch_summary + briefing_text.

Nullable so missions created before Stage 3 keep working — they just
won't have a teaser in dossier views. New generations always populate it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-02
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE missions ADD COLUMN teaser VARCHAR(140)")


def downgrade() -> None:
    op.execute("ALTER TABLE missions DROP COLUMN IF EXISTS teaser")

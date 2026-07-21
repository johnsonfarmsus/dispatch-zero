"""Drop missions.audio_url — the TTS feature is cut, not deferred.

The column was reserved for Kokoro TTS briefing audio (project doc v4).
No synthesis code was ever built and the product decision (June 2026) is
that Dispatch Zero commits to text-only briefings, so the dangling column
goes away rather than sitting as a permanent "maybe later".

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("missions", "audio_url")


def downgrade() -> None:
    # Restores the column shape only; audio_url values are not recoverable
    # (none ever existed — no synthesis code shipped).
    op.add_column(
        "missions",
        sa.Column("audio_url", sa.String(length=400), nullable=True),
    )

"""add share_token to completions

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-27
"""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE completions ADD COLUMN share_token VARCHAR(12)")

    # Backfill any existing rows. Prod has only smoke-test completions at this
    # point, so a Python loop is fine; if this ever runs against a big table,
    # batch it.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM completions WHERE share_token IS NULL")
    ).fetchall()
    for (cid,) in rows:
        conn.execute(
            sa.text("UPDATE completions SET share_token = :t WHERE id = :id"),
            {"t": secrets.token_urlsafe(7), "id": cid},
        )

    op.execute("ALTER TABLE completions ALTER COLUMN share_token SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX ix_completions_share_token ON completions (share_token)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_completions_share_token")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS share_token")

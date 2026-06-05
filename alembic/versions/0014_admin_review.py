"""admin review surface: users.is_admin + submissions.review_note

Two columns to support an in-PWA admin review queue:

- users.is_admin  — boolean flag, default false. Required for the /admin/*
  routes to respond as anything other than 404. Set per-user via
  `python -m dispatchzero.tools.user_admin promote <callsign>`.

- submissions.review_note  — optional short note (<=200 chars) the reviewer
  can attach when returning a submission. Surfaced on the submitter's
  dossier card alongside the RETURNED stamp so they know why.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "submissions",
        sa.Column("review_note", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "review_note")
    op.drop_column("users", "is_admin")

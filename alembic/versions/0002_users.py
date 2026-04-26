"""add users table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("callsign", sa.String(32), nullable=False),
        sa.Column("callsign_lower", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("adventure_style", sa.String(16), nullable=False),
        sa.Column("xp", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rank", sa.String(32), nullable=False, server_default="recruit"),
        sa.Column("missions_this_week", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missions_last_week", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_callsign_lower", "users", ["callsign_lower"])


def downgrade() -> None:
    op.drop_index("ix_users_callsign_lower", table_name="users")
    op.drop_table("users")

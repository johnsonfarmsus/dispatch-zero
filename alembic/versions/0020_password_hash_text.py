"""widen users.password_hash to Text

password_hash was String(255). Argon2id's encoded hash fits comfortably
today, but the cap is a latent footgun: if the hasher params are ever
tuned up (longer salt/output), a hash exceeding 255 chars would be
truncated on insert and silently break verification. Text removes the
bound. (The OSM token columns are already Text.)

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users", "password_hash",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users", "password_hash",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )

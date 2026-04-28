"""drop capture coords + EXIF columns from completions (privacy: not persisted)

These were written at capture time but never read again. Verification still
uses the data live; we just don't store it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-28
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS capture_lat")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS capture_lng")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS capture_accuracy_m")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS had_exif")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS exif_datetime_delta_seconds")
    op.execute("ALTER TABLE completions DROP COLUMN IF EXISTS had_exif_gps")


def downgrade() -> None:
    # Recreated as nullable; previous values are gone.
    op.execute("ALTER TABLE completions ADD COLUMN capture_lat DOUBLE PRECISION")
    op.execute("ALTER TABLE completions ADD COLUMN capture_lng DOUBLE PRECISION")
    op.execute("ALTER TABLE completions ADD COLUMN capture_accuracy_m DOUBLE PRECISION")
    op.execute("ALTER TABLE completions ADD COLUMN had_exif BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE completions ADD COLUMN exif_datetime_delta_seconds INTEGER")
    op.execute("ALTER TABLE completions ADD COLUMN had_exif_gps BOOLEAN NOT NULL DEFAULT FALSE")

"""consolidate location_reason enum from 4 values to 2

Background: the survey originally exposed four downvote reasons (gone /
not_found / inaccessible / unsafe). For routing purposes only two outcomes
matter — "stop sending people here" or "user couldn't find it" — so we
collapsed them:

    gone, inaccessible, unsafe → unreachable
    not_found                  → not_found  (unchanged)

The column type is unchanged (VARCHAR(16)); only the value domain shrinks.
Backfill is idempotent — safe to re-run.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-02
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Collapse retired reason codes into 'unreachable'. Leaves NULL and
    # 'not_found' rows untouched.
    op.execute(
        "UPDATE completions SET location_reason='unreachable' "
        "WHERE location_reason IN ('gone', 'inaccessible', 'unsafe')"
    )


def downgrade() -> None:
    # No safe downgrade — we cannot recover which of gone/inaccessible/unsafe
    # an 'unreachable' row originally was. Map them all to 'gone' as the
    # closest single-value equivalent.
    op.execute(
        "UPDATE completions SET location_reason='gone' "
        "WHERE location_reason='unreachable'"
    )

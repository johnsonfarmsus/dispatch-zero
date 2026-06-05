"""osm publish surface: credentials + audit log

Two tables that back the OSM integration:

- osm_credentials  — Singleton (id always 1). Holds the OAuth 2.0 tokens
  we get back from OSM after Trevor connects the DispatchZero account.
  access_token is short-lived; refresh_token is long-lived and is what
  lets us mint new access tokens without re-prompting. Only one account
  publishes, so a single row suffices.

- osm_publications — Audit log. One row per Approve+OSM action,
  recording the changeset ID, node ID, the tags we sent, who approved,
  and whether it was a dry-run. The daily cap query reads this table
  (count rows from today where dry_run=false).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "osm_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Tokens are stored as-is (no encryption at rest). This is the same
        # posture we have on password hashes — if the DB is compromised, the
        # blast radius is the same regardless. Future enhancement could
        # encrypt with a key derived from session_secret.
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # OSM identity we're authenticated as. Pulled from /api/0.6/user/details
        # right after the first token grant so we can show "Connected as
        # DispatchZero" in the admin UI.
        sa.Column("osm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("osm_username", sa.String(length=200), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Enforce single-row table by checking id=1.
        sa.CheckConstraint("id = 1", name="osm_credentials_singleton"),
    )

    op.create_table(
        "osm_publications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            UUID(as_uuid=True),
            sa.ForeignKey("submissions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # OSM-side identifiers. Both nullable because dry-run rows don't
        # have either yet (no real API call was made).
        sa.Column("changeset_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        # The exact tags we sent (or would have sent in dry-run mode).
        # Stored as JSONB so we can audit + re-render the same tagging if
        # a downstream tool wants to.
        sa.Column("tags_json", JSONB(), nullable=False),
        # Snapshot of coordinates at publish time (useful if the linked Place
        # gets edited or deleted later).
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "published_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # True = changeset XML was generated and logged but NOT actually
        # POSTed to OSM. Dry-run rows do not count against the daily cap.
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_osm_publications_published_at",
        "osm_publications",
        ["published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_osm_publications_published_at", table_name="osm_publications")
    op.drop_table("osm_publications")
    op.drop_table("osm_credentials")

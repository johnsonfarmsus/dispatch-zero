"""external link on submissions + OSM dedup tracking

Three columns layered on the existing schema:

- submissions.external_link  — optional URL the submitter typed in the
  new Link field on the report form. Used at publish time to derive
  wikipedia= (if it's a wikipedia.org URL) or website= tags on the
  OSM node. Also surfaced to the admin in the review queue so the
  reviewer can verify the place before approving.

- places.osm_published_node_id  — set after a successful OSM publish.
  Lets us refuse to re-publish a place that's already on OSM, even if
  it later shows up via a different code path (a completion candidate,
  a re-submission). Nullable: NULL means "never been to OSM."

- osm_publications.place_id  — back-link from the audit row to the Place
  that was published. Existing submission_id stays but is set NULL if
  the Submission gets deleted; place_id gives us a stable link via the
  Place row that's harder to lose.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("external_link", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("osm_published_node_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "osm_publications",
        sa.Column("place_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "osm_publications_place_id_fkey",
        "osm_publications",
        "places",
        ["place_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "osm_publications_place_id_fkey", "osm_publications", type_="foreignkey"
    )
    op.drop_column("osm_publications", "place_id")
    op.drop_column("places", "osm_published_node_id")
    op.drop_column("submissions", "external_link")

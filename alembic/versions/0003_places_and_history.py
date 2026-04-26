"""add places and user_place_history tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE places (
            id UUID PRIMARY KEY,
            osm_type VARCHAR(8) NOT NULL,
            osm_id BIGINT NOT NULL,
            name VARCHAR(200),
            category VARCHAR(16) NOT NULL,
            coordinates geography(Point, 4326) NOT NULL,
            tags JSONB NOT NULL DEFAULT '{}',
            description TEXT,
            wikidata_id VARCHAR(16),
            quality_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            location_thumbs_up INTEGER NOT NULL DEFAULT 0,
            location_thumbs_down INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_places_osm UNIQUE (osm_type, osm_id)
        )
    """)
    op.execute("CREATE INDEX ix_places_status_category ON places (status, category)")
    op.execute("CREATE INDEX ix_places_coordinates ON places USING gist (coordinates)")
    op.execute("""
        CREATE TABLE user_place_history (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            last_completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_place UNIQUE (user_id, place_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_place_history")
    op.execute("DROP TABLE IF EXISTS places")

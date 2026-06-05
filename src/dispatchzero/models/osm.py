"""OSM integration models: project-account credentials + publish audit log.

See alembic/versions/0016_osm_integration.py for the schema rationale.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class OsmCredentials(Base):
    """Singleton row: only one OSM project account publishes for this app."""

    __tablename__ = "osm_credentials"
    __table_args__ = (
        CheckConstraint("id = 1", name="osm_credentials_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    osm_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    osm_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OsmPublication(Base):
    """One row per Approve+OSM action, dry-run OR real."""

    __tablename__ = "osm_publications"
    __table_args__ = (
        Index("ix_osm_publications_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Back-link to the Place that was published. Survives if the Submission
    # later gets deleted (foreign key is SET NULL on delete). Used by the
    # admin queue's "already on OSM" gate as a defense-in-depth check
    # alongside places.osm_published_node_id.
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Null on dry-run rows; populated on real publishes.
    changeset_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Tags we sent (or would have sent), as a JSON object.
    tags_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # True = changeset XML was generated and logged but NOT POSTed to OSM.
    # Dry-run rows are excluded from the daily-cap count.
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

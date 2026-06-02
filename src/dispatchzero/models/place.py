import uuid
from datetime import datetime
from enum import StrEnum

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class PlaceCategory(StrEnum):
    MURAL = "mural"
    SCULPTURE = "sculpture"
    MEMORIAL = "memorial"
    HISTORIC = "historic"
    VIEWPOINT = "viewpoint"
    CHURCH = "church"


class PlaceStatus(StrEnum):
    ACTIVE = "active"
    FLAGGED = "flagged"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class Place(Base):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    osm_type: Mapped[str] = mapped_column(String(8), nullable=False)  # node|way|relation
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    coordinates = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    wikidata_id: Mapped[str | None] = mapped_column(String(16), nullable=True)

    quality_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    location_thumbs_up: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    location_thumbs_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("osm_type", "osm_id", name="uq_places_osm"),
        Index("ix_places_status_category", "status", "category"),
        Index(
            "ix_places_coordinates",
            "coordinates",
            postgresql_using="gist",
        ),
    )

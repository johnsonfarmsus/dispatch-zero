import uuid
from datetime import datetime
from enum import StrEnum

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
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
    PARK = "park"                    # parks, waterfalls, trailheads — outdoor scenic
    INFRASTRUCTURE = "infrastructure"  # dams, bridges, towers — engineering landmarks
    CIVIC = "civic"                  # post offices — small-town civic landmarks


class PlaceStatus(StrEnum):
    ACTIVE = "active"
    FLAGGED = "flagged"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    # PENDING: place was submitted by a community user and is awaiting maintainer
    # review. Not dispatchable until the linked Submission's status flips to
    # APPROVED (which also flips the Place to ACTIVE). On REJECTED submissions
    # the Place can be left at PENDING indefinitely or moved to RETIRED — either
    # way, no future dispatch will land here.
    PENDING = "pending"


class Place(Base):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Originally VARCHAR(8) sized for OSM's "node"/"way"/"relation". Widened to
    # 16 so we can use longer source tags like "community" (POI submissions)
    # and any future imports (overture, hifld, etc.) without another migration.
    osm_type: Mapped[str] = mapped_column(String(16), nullable=False)
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

    # Community-submission attribution. Non-null for places that came in via
    # POST /submissions/capture (osm_type='community'). Used by
    # services.missions._user_has_visited so a user dispatched to a place they
    # submitted gets the repeat-visit briefing framing — the submission photo
    # counted as their first visit. Null for everything else (Overpass /
    # Wikipedia / GNIS).
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The optional 140-char description the user wrote at submission time.
    # Fed into the briefing prompt as flavor for places where we have no
    # external description (Wikipedia / Wikidata blurb).
    submission_description: Mapped[str | None] = mapped_column(
        String(140), nullable=True
    )

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

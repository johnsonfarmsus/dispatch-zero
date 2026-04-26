import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class MissionStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_REGEN = "needs_regen"
    RETIRED = "retired"


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )
    adventure_style: Mapped[str] = mapped_column(String(16), nullable=False)
    dispatch_summary: Mapped[str] = mapped_column(String(400), nullable=False)
    briefing_text: Mapped[str] = mapped_column(String(2200), nullable=False)
    clue: Mapped[str | None] = mapped_column(String(240), nullable=True)
    badge_framing: Mapped[str | None] = mapped_column(String(120), nullable=True)

    mission_thumbs_up: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mission_thumbs_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    implicit_completions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    audio_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        Index("ix_missions_place_style_status", "place_id", "adventure_style", "status"),
    )

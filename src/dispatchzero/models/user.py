import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class AdventureStyle(StrEnum):
    PULP = "pulp"
    AGENCY = "agency"
    GUILD = "guild"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    callsign: Mapped[str] = mapped_column(String(32), nullable=False)
    callsign_lower: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    adventure_style: Mapped[str] = mapped_column(String(16), nullable=False)

    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank: Mapped[str] = mapped_column(String(32), default="recruit", nullable=False)
    missions_this_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missions_last_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_callsign_lower", "callsign_lower"),)

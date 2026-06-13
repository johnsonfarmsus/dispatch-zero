import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
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
    # Text, not String(255): an argon2 hash fits today but tuning the hasher
    # params up could exceed 255 and silently truncate. See migration 0020.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    adventure_style: Mapped[str] = mapped_column(String(16), nullable=False)

    missions_this_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missions_last_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # When true, /admin/* routes respond normally; when false, they 404.
    # Flipped per-user via `python -m dispatchzero.tools.user_admin promote`
    # (see migration 0014 + tools/user_admin.py). Default false; signup
    # never sets this true.
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_callsign_lower", "callsign_lower"),)

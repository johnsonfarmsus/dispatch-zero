import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

CallsignStr = Annotated[
    str,
    StringConstraints(pattern=r"^[a-zA-Z0-9_-]{3,32}$"),
]
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]
AdventureStyle = Literal["pulp", "agency", "guild"]


class SignupIn(BaseModel):
    callsign: CallsignStr
    password: PasswordStr
    adventure_style: AdventureStyle


class LoginIn(BaseModel):
    callsign: CallsignStr
    password: PasswordStr


class MeOut(BaseModel):
    id: uuid.UUID
    callsign: str
    adventure_style: str
    # completions_count covers BOTH verified mission completions AND approved
    # community submissions — both are "real things the user did in the
    # world." See services.mission_flow.user_completions_count.
    completions_count: int = 0
    missions_this_week: int = 0
    # Integer rank 0..10 derived from completions_count; the rank NAME is
    # rendered on the frontend per adventure_style.
    rank: int = 0
    # Community submissions awaiting review. Surfaced on the home screen
    # next to completions so the user can see "1 pending" alongside their
    # main count. When a submission's reviewed (approved or returned),
    # it leaves this count and either joins completions_count (approved) or
    # just lives on in the dossier (returned).
    pending_submissions: int = 0

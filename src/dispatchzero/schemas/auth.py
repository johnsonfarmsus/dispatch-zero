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
    xp: int
    rank: str

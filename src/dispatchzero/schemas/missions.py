import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

AdventureStyle = Literal["pulp", "agency", "guild"]


class MissionContent(BaseModel):
    """The structured payload Ollama returns. Fields match the prompt contract."""

    dispatch_summary: Annotated[str, Field(min_length=1, max_length=400)]
    briefing_text: Annotated[str, Field(min_length=1, max_length=2200)]
    clue: Annotated[str | None, Field(max_length=240)] = None
    badge_framing: Annotated[str | None, Field(max_length=120)] = None


class MissionGenerateIn(BaseModel):
    place_id: uuid.UUID
    adventure_style: AdventureStyle | None = None  # defaults to user's profile


class PlaceMini(BaseModel):
    id: uuid.UUID
    name: str | None
    category: str
    description: str | None = None
    lat: float
    lng: float


class MissionOut(BaseModel):
    id: uuid.UUID
    place_id: uuid.UUID
    place: PlaceMini
    adventure_style: str
    dispatch_summary: str
    briefing_text: str
    clue: str | None
    badge_framing: str | None
    audio_url: str | None
    ai_model: str | None
    status: str

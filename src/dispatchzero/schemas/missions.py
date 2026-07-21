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
    # One in-voice sentence (up to 140 chars) that names the place and gives a
    # hook — shown in the candidate-list UI before the operative picks. Nullable
    # for backward compat with pre-Stage-3 cached missions; new generations
    # always include it.
    teaser: Annotated[str | None, Field(max_length=140)] = None


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
    teaser: str | None
    ai_model: str | None
    status: str


class CandidateOut(BaseModel):
    """One entry in the list returned by POST /missions/candidates.

    These are DISCOVERED places, not yet generated missions — the briefing
    is generated only when the user accepts one (POST /candidates/accept),
    so we don't burn N sequential generations (~40s each on the single-GPU
    OLMo box) for candidates the user won't pick. The card shows place +
    distance + a short preview, which is enough to choose."""
    place_id: uuid.UUID
    place_name: str
    place_category: str
    preview: str | None       # short description for the card (if any)
    distance_m: int           # great-circle distance from the request lat/lng
    bearing_compass: str      # "N" / "NE" / ... — coarse 8-point compass


class CandidatesOut(BaseModel):
    """Wrapper for the candidates response. `empty_message` is populated only
    when no candidates were found — gives the frontend an honest in-voice
    line ('No fresh candidates within 5 km. The nearest unfamiliar territory
    is to the east, ~28 km. Try requesting from there.')."""
    candidates: list[CandidateOut]
    empty_message: str | None = None

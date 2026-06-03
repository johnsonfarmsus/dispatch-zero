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
    audio_url: str | None
    ai_model: str | None
    status: str


class CandidateOut(BaseModel):
    """One entry in the list returned by POST /missions/candidates. Carries
    enough for the list UI to render a card AND for the accept call to
    promote the pre-generated mission to active dispatch.

    `mission_id` is already a real persisted Mission row — accepting just
    flips the user's flow into transit. The other candidates' missions stay
    in the library for future users at the same place."""
    mission_id: uuid.UUID
    place_id: uuid.UUID
    place_name: str
    place_category: str
    teaser: str | None
    distance_m: int           # great-circle distance from the request lat/lng
    bearing_compass: str      # "N" / "NE" / ... — coarse 8-point compass


class CandidatesOut(BaseModel):
    """Wrapper for the candidates response. `empty_message` is populated only
    when no candidates were found — gives the frontend an honest in-voice
    line ('No fresh candidates within 5 km. The nearest unfamiliar territory
    is to the east, ~28 km. Try requesting from there.')."""
    candidates: list[CandidateOut]
    empty_message: str | None = None

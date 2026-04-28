import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

LocationReason = Literal["gone", "not_found", "inaccessible", "unsafe"]


class MissionRequestIn(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    radius_m: Annotated[int, Field(ge=100, le=10_000)] = 2000
    adventure_style: Literal["pulp", "agency", "guild"] | None = None


class CompletionOut(BaseModel):
    id: uuid.UUID
    mission_id: uuid.UUID
    place_id: uuid.UUID
    verified: bool
    photo_url: str | None
    completed_at: str  # ISO 8601
    share_token: str


class DebriefOut(BaseModel):
    completion: CompletionOut
    user_completions_count: int
    user_missions_this_week: int


class RateIn(BaseModel):
    location_rating: Literal["up", "down"] | None = None
    mission_rating: Literal["up", "down"] | None = None
    location_reason: LocationReason | None = None


class CompletionListItem(BaseModel):
    """A single row in the user's history dossier.

    Carries everything needed to render the list (place name, date) AND to
    drive the per-completion detail view (id + share_token for Save Card and
    Copy Share Text actions). Mission's badge_framing is pulled along so the
    detail screen can show what was earned.
    """
    id: uuid.UUID
    place_id: uuid.UUID
    place_name: str | None
    place_category: str
    completed_at: str  # ISO 8601
    share_token: str
    badge_framing: str | None
    adventure_style: str

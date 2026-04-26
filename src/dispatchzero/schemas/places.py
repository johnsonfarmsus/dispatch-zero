import uuid

from pydantic import BaseModel


class PlaceOut(BaseModel):
    id: uuid.UUID
    osm_type: str
    osm_id: int
    name: str | None
    category: str
    description: str | None
    wikidata_id: str | None
    thumbs_up: int
    thumbs_down: int

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class CrossingEventIn(BaseModel):
    """
    Any sensor/camera/guard report anywhere along the border can submit this —
    it no longer needs to match a pre-registered checkpoint_id. The server
    figures out where it is relative to the border corridor and the nearest
    known checkpoint.
    """

    latitude: float = Field(..., ge=-90, le=90, example=11.0050)
    longitude: float = Field(..., ge=-180, le=180, example=-1.1050)
    timestamp: Optional[datetime] = None
    estimated_headcount: int = Field(1, ge=0)
    confidence_score: float = Field(1.0, ge=0.0, le=1.0)
    source: str = Field("manual", example="camera")

    # Optional manual override, e.g. a guard confirming this was at a
    # known post. If omitted, the server classifies it automatically.

    crossing_type_override: Optional[str] = None


class CrossingEventOut(BaseModel):
    id: int
    latitude: float
    longitude: float
    grid_cell: str
    neighbor_country: Optional[str] = None
    nearest_checkpoint_code: Optional[str] = None
    distance_to_checkpoint_m: Optional[float] = None
    timestamp: datetime
    estimated_headcount: int
    crossing_type: str
    confidence_score: float
    source: str

    class Config:
        from_attributes = True


class CheckpointOut(BaseModel):
    code: str
    name: str
    latitude: float
    longitude: float
    is_official: bool
    neighboring_country: Optional[str] = None

    class Config:
        from_attributes = True

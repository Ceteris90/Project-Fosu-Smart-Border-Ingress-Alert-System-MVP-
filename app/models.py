from sqlalchemy import column, integer, string, float, Datetime, boolean
from datetime import datetime
from .database import Base

class Checkpoint(Base):
     """
    A known border post or monitored route.
    is_official=True  -> a legal, staffed port of entry (e.g. Aflao, Paga, Elubo)
    is_official=False -> an informal/unapproved route being monitored
    """

    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    is_official = Column(Boolean, default=True)
    neighboring_country = Column(String, nullable=True)


class CrossingEvent(Base):
    """
    A single logged ingress/egress event, located anywhere along the
    monitored border corridor (not limited to pre-registered checkpoints).
    """

    __tablename__ = "crossing_events"

    id = Column(Integer, primary_key=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    grid_cell = Column(String, index=True, nullable=False)  # ~1km bucket, for hotspot aggregation
    neighbor_country = Column(String, nullable=True)  # Togo | Burkina Faso | Côte d'Ivoire
    nearest_checkpoint_code = Column(String, nullable=True)
    distance_to_checkpoint_m = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    estimated_headcount = Column(Integer, default=1)
    crossing_type = Column(String, default="unknown")  # approved | unapproved_route | outside_corridor
    confidence_score = Column(Float, default=1.0)
    source = Column(String, default="manual")  # camera | sensor | guard | manual

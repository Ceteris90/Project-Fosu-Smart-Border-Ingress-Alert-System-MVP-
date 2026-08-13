"""
Geofence engine for Project Fosu.

Instead of only recognizing events at a handful of pre-registered
checkpoints, this classifies ANY incoming (lat, lon) against the full
border corridor for Ghana — so a sensor/camera/report anywhere along
the ~1,650km border can be logged and located correctly.

Uses Shapely for the containment/nearest-point math. In production with
PostGIS, this same logic becomes ST_DWithin / ST_Distance SQL queries
instead of in-process Python — the classify() interface stays the same.
"""

import json
import math
from dataclasses import dataclass
from typing import Optional

from shapely.geometry import shape, Point
from shapely.ops import nearest_points

CORRIDOR_PATH = "data/ghana_border_corridor.geojson"
BORDERLINE_PATH = "data/ghana_borders.geojson"

# Grid cell size for hotspot aggregation, in degrees (~1.1km at this latitude).
GRID_CELL_DEG = 0.01

# A point within this distance (meters) of a registered checkpoint counts
# as "at" that checkpoint (i.e. official port of entry traffic).
CHECKPOINT_MATCH_RADIUS_M = 1500

@dataclass
class GeofenceResult:
    in_monitored_corridor: bool
    neighbor_country: Optional[str]
    nearest_checkpoint_code: Optional[str]
    nearest_checkpoint_name: Optional[str]
    distance_to_checkpoint_m: Optional[float]
    is_at_official_checkpoint: bool
    grid_cell: str


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class GeofenceEngine:
    def __init__(self, checkpoints=None):
        with open(CORRIDOR_PATH) as f:
            corridor_geojson = json.load(f)
        self.corridors = [
            (feat["properties"]["neighbor"], shape(feat["geometry"]))
            for feat in corridor_geojson["features"]
        ]
        # checkpoints: list of dicts with code, name, latitude, longitude
        self.checkpoints = checkpoints or []

    def set_checkpoints(self, checkpoints):
        self.checkpoints = checkpoints

    def grid_cell_for(self, lat: float, lon: float) -> str:
        gy = round(lat / GRID_CELL_DEG) * GRID_CELL_DEG
        gx = round(lon / GRID_CELL_DEG) * GRID_CELL_DEG
        return f"{gy:.2f}_{gx:.2f}"

    def classify(self, lat: float, lon: float) -> GeofenceResult:
        pt = Point(lon, lat)

        in_corridor = False
        matched_neighbor = None
        for neighbor, poly in self.corridors:
            if poly.contains(pt):
                in_corridor = True
                matched_neighbor = neighbor
                break

        # Find nearest registered checkpoint (regardless of corridor match,
        # useful for flagging interior/incorrect reports too).
        nearest_code = nearest_name = None
        nearest_dist = None
        for cp in self.checkpoints:
            d = _haversine_m(lat, lon, cp["latitude"], cp["longitude"])
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest_code = cp["code"]
                nearest_name = cp["name"]

        is_official = bool(nearest_dist is not None and nearest_dist <= CHECKPOINT_MATCH_RADIUS_M)

        return GeofenceResult(
            in_monitored_corridor=in_corridor,
            neighbor_country=matched_neighbor,
            nearest_checkpoint_code=nearest_code,
            nearest_checkpoint_name=nearest_name,
            distance_to_checkpoint_m=round(nearest_dist, 1) if nearest_dist is not None else None,
            is_at_official_checkpoint=is_official,
            grid_cell=self.grid_cell_for(lat, lon),
        )


geofence_engine = GeofenceEngine()
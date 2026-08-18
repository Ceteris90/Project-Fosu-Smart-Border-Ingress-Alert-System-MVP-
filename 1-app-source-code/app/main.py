"""
Project Fosu — Ingress Logging API (whole-border geofence version)

Any report — camera, sensor, or guard — can come from anywhere along
Ghana's ~1,650km land border, not just a handful of pre-registered posts.
The server classifies each point using the geofence engine (app/geofence.py)
against the real border corridor built from country boundary data
(scripts/build_border_geometry.py).

Run with:
    uvicorn app.main:app --reload --port 8000

Docs auto-generated at http://localhost:8000/docs
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from . import models, schemas
from .database import engine, get_db, Base
from .geofence import BORDERLINE_PATH, CORRIDOR_PATH, geofence_engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Project Fosu - Border Ingress API",
    description="Whole-border ingestion, geofencing, aggregation, and alerting API.",
    version="0.2.0",
)

# --- Alert threshold config ---
ALERT_WINDOW_MINUTES = 60
ALERT_HEADCOUNT_THRESHOLD = 15  # total estimated headcount in a single grid cell to trigger alert

# Known official ports of entry (still tracked, but no longer the only
# valid source of data — anything in the corridor is now logged).
SEED_CHECKPOINTS = [
    dict(code="GH_AFLAO_01", name="Aflao", latitude=6.1219, longitude=1.1974,
         is_official=True, neighboring_country="Togo"),
    dict(code="GH_PAGA_01", name="Paga", latitude=10.9974, longitude=-1.1181,
         is_official=True, neighboring_country="Burkina Faso"),
    dict(code="GH_ELUBO_01", name="Elubo", latitude=5.1996, longitude=-2.8973,
         is_official=True, neighboring_country="Côte d'Ivoire"),
    dict(code="GH_SAMPA_01", name="Sampa", latitude=7.9509, longitude=-2.6939,
         is_official=True, neighboring_country="Côte d'Ivoire"),
]


def seed_checkpoints(db: Session):
    for cp in SEED_CHECKPOINTS:
        exists = db.query(models.Checkpoint).filter_by(code=cp["code"]).first()
        if not exists:
            db.add(models.Checkpoint(**cp))
    db.commit()


@app.on_event("startup")
def on_startup():
    db = next(get_db())
    seed_checkpoints(db)
    checkpoints = [
        {"code": c.code, "name": c.name, "latitude": c.latitude, "longitude": c.longitude}
        for c in db.query(models.Checkpoint).all()
    ]
    geofence_engine.set_checkpoints(checkpoints)


@app.get("/", tags=["meta"])
def root():
    return {"service": "Project Fosu", "status": "ok", "mode": "whole-border geofence"}


@app.get("/checkpoints", response_model=List[schemas.CheckpointOut], tags=["checkpoints"])
def list_checkpoints(db: Session = Depends(get_db)):
    return db.query(models.Checkpoint).all()


@app.get("/border-geometry", tags=["checkpoints"])
def border_geometry():
    """Serves the border line + corridor GeoJSON for map rendering."""
    import json
    with open(BORDERLINE_PATH) as f:
        lines = json.load(f)
    with open(CORRIDOR_PATH) as f:
        corridor = json.load(f)
    return {"lines": lines, "corridor": corridor}


@app.post("/ingest", response_model=schemas.CrossingEventOut, tags=["ingestion"])
def ingest_event(event: schemas.CrossingEventIn, db: Session = Depends(get_db)):
    """
    Module A: receives a crossing event from ANY point along the border —
    classifies it against the real geofence rather than requiring a
    pre-registered checkpoint_id.
    """
    result = geofence_engine.classify(event.latitude, event.longitude)

    if not result.in_monitored_corridor:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Coordinates ({event.latitude}, {event.longitude}) are not within the "
                f"monitored border corridor. Nearest checkpoint: "
                f"{result.nearest_checkpoint_name} ({result.distance_to_checkpoint_m:.0f}m away)."
            ),
        )

    if event.crossing_type_override:
        crossing_type = event.crossing_type_override
    elif result.is_at_official_checkpoint:
        crossing_type = "approved"
    else:
        crossing_type = "unapproved_route"

    db_event = models.CrossingEvent(
        latitude=event.latitude,
        longitude=event.longitude,
        grid_cell=result.grid_cell,
        neighbor_country=result.neighbor_country,
        nearest_checkpoint_code=result.nearest_checkpoint_code,
        distance_to_checkpoint_m=result.distance_to_checkpoint_m,
        timestamp=event.timestamp or datetime.utcnow(),
        estimated_headcount=event.estimated_headcount,
        crossing_type=crossing_type,
        confidence_score=event.confidence_score,
        source=event.source,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    alert = check_threshold_alert(db, result.grid_cell)
    if alert:
        # In production: push to SMS gateway / Telegram bot here.
        print(f"[ALERT] {alert}")

    return db_event


@app.get("/crossings", response_model=List[schemas.CrossingEventOut], tags=["query"])
def list_crossings(
    neighbor_country: Optional[str] = None,
    crossing_type: Optional[str] = None,
    hours: int = 24,
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(models.CrossingEvent).filter(models.CrossingEvent.timestamp >= since)
    if neighbor_country:
        q = q.filter(models.CrossingEvent.neighbor_country == neighbor_country)
    if crossing_type:
        q = q.filter(models.CrossingEvent.crossing_type == crossing_type)
    return q.order_by(models.CrossingEvent.timestamp.desc()).all()


@app.get("/stats/daily", tags=["analytics"])
def daily_stats(days: int = 7, db: Session = Depends(get_db)):
    """Module C: 'How many people crossed today / this week, by type?'"""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.date(models.CrossingEvent.timestamp).label("day"),
            models.CrossingEvent.crossing_type,
            func.sum(models.CrossingEvent.estimated_headcount).label("total_headcount"),
            func.count(models.CrossingEvent.id).label("event_count"),
        )
        .filter(models.CrossingEvent.timestamp >= since)
        .group_by("day", models.CrossingEvent.crossing_type)
        .order_by("day")
        .all()
    )
    return [
        {
            "day": str(r.day),
            "crossing_type": r.crossing_type,
            "total_headcount": int(r.total_headcount or 0),
            "event_count": r.event_count,
        }
        for r in rows
    ]


@app.get("/stats/hotspots", tags=["analytics"])
def hotspot_stats(hours: int = 24, min_events: int = 1, db: Session = Depends(get_db)):
    """
    Module B/C: aggregates events by grid cell to surface hotspots
    ANYWHERE along the border — not just at named checkpoints. This is
    what lets command staff spot a new informal crossing route forming.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(
            models.CrossingEvent.grid_cell,
            models.CrossingEvent.neighbor_country,
            func.avg(models.CrossingEvent.latitude).label("lat"),
            func.avg(models.CrossingEvent.longitude).label("lon"),
            func.sum(models.CrossingEvent.estimated_headcount).label("total_headcount"),
            func.count(models.CrossingEvent.id).label("event_count"),
            func.max(models.CrossingEvent.distance_to_checkpoint_m).label("distance_to_checkpoint_m"),
        )
        .filter(models.CrossingEvent.timestamp >= since)
        .filter(models.CrossingEvent.crossing_type == "unapproved_route")
        .group_by(models.CrossingEvent.grid_cell, models.CrossingEvent.neighbor_country)
        .having(func.count(models.CrossingEvent.id) >= min_events)
        .order_by(func.sum(models.CrossingEvent.estimated_headcount).desc())
        .all()
    )
    return [
        {
            "grid_cell": r.grid_cell,
            "neighbor_country": r.neighbor_country,
            "latitude": round(r.lat, 5),
            "longitude": round(r.lon, 5),
            "total_headcount": int(r.total_headcount or 0),
            "event_count": r.event_count,
            "distance_to_nearest_checkpoint_m": round(r.distance_to_checkpoint_m, 0) if r.distance_to_checkpoint_m else None,
        }
        for r in rows
    ]


def check_threshold_alert(db: Session, grid_cell: str) -> Optional[str]:
    """Module B: if a grid cell logs unusually high volume, flag it — works anywhere on the border."""
    since = datetime.utcnow() - timedelta(minutes=ALERT_WINDOW_MINUTES)
    total = (
        db.query(func.sum(models.CrossingEvent.estimated_headcount))
        .filter(
            models.CrossingEvent.grid_cell == grid_cell,
            models.CrossingEvent.timestamp >= since,
        )
        .scalar()
    ) or 0

    if total >= ALERT_HEADCOUNT_THRESHOLD:
        return (
            f"Grid cell {grid_cell} logged {total} estimated crossings in the "
            f"last {ALERT_WINDOW_MINUTES} minutes (threshold: {ALERT_HEADCOUNT_THRESHOLD})."
        )
    return None


@app.get("/alerts/check/{grid_cell}", tags=["analytics"])
def alert_check(grid_cell: str, db: Session = Depends(get_db)):
    alert = check_threshold_alert(db, grid_cell)
    return {"grid_cell": grid_cell, "alert": alert}
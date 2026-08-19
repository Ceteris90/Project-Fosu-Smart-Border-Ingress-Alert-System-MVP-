"""
Mock field sensor generator — whole-border version.

Instead of only pinging 5 fixed checkpoints, this samples random points
along the ACTUAL Ghana border lines (data/ghana_borders.geojson) so you
get realistic coverage of the full ~1,650km frontier, with a bias toward
a few "hotspot" clusters to simulate emerging informal routes.

Run (with the API already running on port 8000):
    python scripts/mock_sensor.py --once --n 300
    python scripts/mock_sensor.py --interval 3       # live streaming mode
"""
import argparse
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.ops import substring

API_URL = "http://localhost:8000/ingest"
BORDERLINES_PATH = Path(__file__).resolve().parent.parent / "data" / "ghana_borders.geojson"

# Real official checkpoints, used to bias some traffic toward "approved" crossings.
OFFICIAL_POINTS = [
    (6.1219, 1.1974),    # Aflao
    (10.9974, -1.1181),  # Paga
    (5.1996, -2.8973),   # Elubo
    (7.9509, -2.6939),   # Sampa
]


def load_border_lines():
    with open(BORDERLINES_PATH) as f:
        data = json.load(f)
    lines = []
    for feat in data["features"]:
        geom = shape(feat["geometry"])
        # geom may be a MultiLineString; flatten to individual LineStrings
        if geom.geom_type == "MultiLineString":
            lines.extend(list(geom.geoms))
        else:
            lines.append(geom)
    return lines


def random_point_on_border(lines, hotspot_bias=0.3, hotspots=None):
    """
    Picks a random point along the real border. With some probability,
    picks a point near a fixed set of 'hotspot' coordinates instead —
    simulating an emerging informal crossing cluster rather than fully
    uniform noise.
    """
    if hotspots and random.random() < hotspot_bias:
        lat, lon = random.choice(hotspots)
        # jitter by a few hundred meters
        return lat + random.uniform(-0.003, 0.003), lon + random.uniform(-0.003, 0.003)

    line = random.choice(lines)
    frac = random.random()
    pt = substring(line, frac, frac, normalized=True)
    lon, lat = pt.x, pt.y
    return lat, lon


def send_event(lat, lon, crossing_type_hint=None, timestamp=None, source=None):
    event_source = source or random.choice(["camera", "sensor", "guard"])
    if event_source == "guard":
        crossing_type_hint = "approved"

    payload = {
        "latitude": lat,
        "longitude": lon,
        "estimated_headcount": random.randint(1, 6),
        "confidence_score": round(random.uniform(0.7, 0.99), 2),
        "source": event_source,
    }
    if crossing_type_hint:
        payload["crossing_type_override"] = crossing_type_hint
    if timestamp:
        payload["timestamp"] = timestamp.isoformat() + "Z"

    try:
        r = requests.post(API_URL, json=payload, timeout=5)
        r.raise_for_status()
        data = r.json()
        print(f"OK  ({lat:.4f},{lon:.4f}) -> {data['crossing_type']:16s} "
              f"near {data.get('nearest_checkpoint_code')} "
              f"[{data.get('neighbor_country')}]")
    except requests.RequestException as e:
        detail = getattr(e.response, "text", "") if hasattr(e, "response") and e.response else ""
        print(f"ERR ({lat:.4f},{lon:.4f}): {e} {detail}")


def seed_history(n: int, lines, hotspots):
    now = datetime.utcnow()
    for _ in range(n):
        # 25% of traffic goes through official points to simulate legitimate flow
        if random.random() < 0.25:
            lat, lon = random.choice(OFFICIAL_POINTS)
            lat += random.uniform(-0.002, 0.002)
            lon += random.uniform(-0.002, 0.002)
            crossing_type_hint = "approved"
        else:
            lat, lon = random_point_on_border(lines, hotspots=hotspots)
            crossing_type_hint = "unapproved_route"
        ts = now - timedelta(minutes=random.randint(0, 48 * 60))
        send_event(lat, lon, crossing_type_hint=crossing_type_hint, timestamp=ts)


def live_loop(interval, lines, hotspots):
    print(f"Simulating live sensor pings every {interval}s across the whole border. Ctrl+C to stop.")
    while True:
        if random.random() < 0.25:
            lat, lon = random.choice(OFFICIAL_POINTS)
            lat += random.uniform(-0.002, 0.002)
            lon += random.uniform(-0.002, 0.002)
            crossing_type_hint = "approved"
        else:
            lat, lon = random_point_on_border(lines, hotspots=hotspots)
            crossing_type_hint = "unapproved_route"
        send_event(lat, lon, crossing_type_hint=crossing_type_hint)
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Bulk-seed historical data then exit")
    parser.add_argument("--n", type=int, default=200, help="Number of events to seed with --once")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between live pings")
    args = parser.parse_args()

    lines = load_border_lines()

    # A couple of illustrative "hotspot" coordinates along the Burkina Faso
    # and Togo borders, to simulate an emerging informal-route cluster for
    # the dashboard/alert demo. Purely synthetic — not real intelligence.
    hotspots = [
        (11.0050, -1.1050),  # near Paga, Burkina Faso side
        (7.5000, 0.5500),    # mid Togo border
    ]

    if args.once:
        seed_history(args.n, lines, hotspots)
    else:
        live_loop(args.interval, lines, hotspots)

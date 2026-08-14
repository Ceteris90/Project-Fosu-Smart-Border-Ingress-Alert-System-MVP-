"""
Builds the full Ghana border geometry (not just fixed checkpoints).

For each neighboring country, computes the shared boundary line between
Ghana's polygon and the neighbor's polygon, then buffers it into a
monitoring corridor (a polygon strip a few km wide straddling the border).

Output: data/ghana_borders.geojson
    One feature per neighbor, each with:
      - "line" geometry (the border itself, for drawing on the map)
      - properties: neighbor name, length_km

Also writes data/ghana_border_corridor.geojson: the buffered polygon
version used for point-in-corridor geofence checks.

Run once (or whenever you want to regenerate):
    python scripts/build_border_geometry.py
"""
import json
import geopandas as gpd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

SRC = "data/countries.geojson"
NEIGHBORS = {
    "TGO": "Togo",
    "BFA": "Burkina Faso",
    "CIV": "Côte d'Ivoire",
}
# Width of the monitoring corridor straddling the border line, in km.
CORRIDOR_KM = 5


def load_country(feature_id: str):
    with open(SRC) as f:
        data = json.load(f)
    for feat in data["features"]:
        if feat.get("id") == feature_id:
            return shape(feat["geometry"])
    raise ValueError(f"{feature_id} not found in {SRC}")


def main():
    ghana = load_country("GHA")

    border_lines = []
    corridor_polys = []

    for iso, name in NEIGHBORS.items():
        neighbor = load_country(iso)
        # The shared border is where the two country polygons' boundaries touch/overlap.
        shared = ghana.boundary.intersection(neighbor.boundary)
        if shared.is_empty:
            print(f"WARNING: no shared boundary found for {name} ({iso})")
            continue

        border_lines.append({"iso": iso, "name": name, "geom": shared})

        # Project to a metric CRS (Web Mercator) to buffer in real km, then back to WGS84.
        gdf = gpd.GeoSeries([shared], crs="EPSG:4326").to_crs(epsg=3857)
        buffered = gdf.buffer(CORRIDOR_KM * 1000)
        buffered_wgs84 = buffered.to_crs(epsg=4326).iloc[0]
        corridor_polys.append({"iso": iso, "name": name, "geom": buffered_wgs84})

    # Write border lines geojson
    line_features = []
    for b in border_lines:
        length_km = gpd.GeoSeries([b["geom"]], crs="EPSG:4326").to_crs(epsg=3857).length.iloc[0] / 1000
        line_features.append({
            "type": "Feature",
            "properties": {"iso": b["iso"], "neighbor": b["name"], "length_km": round(length_km, 1)},
            "geometry": mapping(b["geom"]),
        })
    with open("data/ghana_borders.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": line_features}, f)

    # Write corridor polygons geojson (used for geofence containment checks)
    corridor_features = []
    for c in corridor_polys:
        corridor_features.append({
            "type": "Feature",
            "properties": {"iso": c["iso"], "neighbor": c["name"]},
            "geometry": mapping(c["geom"]),
        })
    with open("data/ghana_border_corridor.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": corridor_features}, f)

    print("Wrote data/ghana_borders.geojson and data/ghana_border_corridor.geojson")
    for b in border_lines:
        length_km = gpd.GeoSeries([b["geom"]], crs="EPSG:4326").to_crs(epsg=3857).length.iloc[0] / 1000
        print(f"  {b['name']:20s} ~{length_km:.0f} km shared border")


if __name__ == "__main__":
    main()

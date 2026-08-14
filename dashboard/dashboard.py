"""
Project Fosu — Command Center Dashboard (whole-border version)

Run (with the API already running on port 8000):
    streamlit run dashboard/dashboard.py
"""
import requests
import pandas as pd
import streamlit as st
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Project Fosu — Border Command Dashboard", layout="wide")
st.title("🇬🇭 Project Fosu — Whole-Border Command Dashboard")
st.caption("Prototype MVP · demo data only · geofenced across the full border, not fixed posts")


@st.cache_data(ttl=15)
def fetch_json(path, params=None):
    r = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


col_refresh, _ = st.columns([1, 5])
if col_refresh.button("🔄 Refresh"):
    st.cache_data.clear()

try:
    checkpoints = fetch_json("/checkpoints")
    crossings = fetch_json("/crossings", params={"hours": 48})
    daily_stats = fetch_json("/stats/daily", params={"days": 7})
    hotspots = fetch_json("/stats/hotspots", params={"hours": 48, "min_events": 2})
    geometry = fetch_json("/border-geometry")
except requests.RequestException:
    st.error("Cannot reach the API. Make sure it's running: `uvicorn app.main:app --reload`")
    st.stop()

cp_df = pd.DataFrame(checkpoints)
cross_df = pd.DataFrame(crossings)
stats_df = pd.DataFrame(daily_stats)
hotspot_df = pd.DataFrame(hotspots)

# --- KPIs ---
k1, k2, k3, k4 = st.columns(4)
total_48h = int(cross_df["estimated_headcount"].sum()) if not cross_df.empty else 0
unapproved_48h = (
    int(cross_df.loc[cross_df.crossing_type == "unapproved_route", "estimated_headcount"].sum())
    if not cross_df.empty else 0
)
k1.metric("Total crossings (48h)", total_48h)
k2.metric("Unapproved-route crossings (48h)", unapproved_48h)
k3.metric("Active hotspot clusters", len(hotspot_df))
k4.metric("Events logged (48h)", len(cross_df))

st.divider()

# --- Map ---
st.subheader("Whole-Border Coverage Map")
m = folium.Map(location=[7.9465, -1.0232], zoom_start=7, tiles="CartoDB positron")

# Draw the actual border lines
for feat in geometry["lines"]["features"]:
    folium.GeoJson(
        feat,
        style_function=lambda x: {"color": "#333333", "weight": 2, "dashArray": "4,4"},
        tooltip=f"Border with {feat['properties']['neighbor']} (~{feat['properties']['length_km']} km)",
    ).add_to(m)

# Draw the monitored corridor (buffered zone)
for feat in geometry["corridor"]["features"]:
    folium.GeoJson(
        feat,
        style_function=lambda x: {"color": "#6699cc", "weight": 0, "fillOpacity": 0.08},
    ).add_to(m)

# Official checkpoints
for _, cp in cp_df.iterrows():
    folium.Marker(
        location=[cp["latitude"], cp["longitude"]],
        icon=folium.Icon(color="green", icon="flag"),
        popup=f"<b>{cp['name']}</b> (official)<br>Neighbor: {cp['neighboring_country']}",
    ).add_to(m)

# Heatmap of ALL crossing events (this is the whole-border view — density
# shows up wherever activity is, not just at named posts)
if not cross_df.empty:
    heat_data = cross_df[["latitude", "longitude", "estimated_headcount"]].values.tolist()
    HeatMap(heat_data, radius=18, blur=22, max_zoom=10).add_to(m)

# Explicit hotspot markers for unapproved-route clusters
for _, h in hotspot_df.iterrows():
    folium.CircleMarker(
        location=[h["latitude"], h["longitude"]],
        radius=8 + min(h["total_headcount"], 30) * 0.4,
        color="red",
        fill=True,
        fill_opacity=0.6,
        popup=folium.Popup(
            f"<b>Hotspot</b><br>"
            f"Neighbor: {h['neighbor_country']}<br>"
            f"48h headcount: {h['total_headcount']}<br>"
            f"Events: {h['event_count']}<br>"
            f"Distance to nearest post: {h['distance_to_nearest_checkpoint_m']:.0f} m",
            max_width=250,
        ),
    ).add_to(m)

st_folium(m, width=1100, height=550)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Daily Totals (last 7 days)")
    if not stats_df.empty:
        pivot = stats_df.pivot_table(
            index="day", columns="crossing_type", values="total_headcount", fill_value=0
        )
        st.bar_chart(pivot)
    else:
        st.info("No data yet. Run: python scripts/mock_sensor.py --once --n 200")

with right:
    st.subheader("Top Emerging Hotspots (unapproved routes, 48h)")
    if not hotspot_df.empty:
        st.dataframe(
            hotspot_df[["neighbor_country", "total_headcount", "event_count",
                        "distance_to_nearest_checkpoint_m"]].head(10),
            use_container_width=True,
        )
    else:
        st.info("No hotspot clusters detected yet.")

st.divider()
st.subheader("Raw Event Log (last 48h)")
st.dataframe(cross_df, use_container_width=True)

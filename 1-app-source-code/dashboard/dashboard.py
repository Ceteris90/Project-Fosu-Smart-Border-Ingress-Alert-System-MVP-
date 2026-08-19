"""Project Fosu whole-border command dashboard.

Run with the API available on port 8000:
    streamlit run dashboard/dashboard.py
"""
import base64
import binascii
import hashlib
import hmac
import os
import time
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from folium.plugins import HeatMap
from streamlit_folium import st_folium

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
ASSET_DIR = Path(__file__).parent / "assets"
SOURCE_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = (
    SOURCE_ROOT.parent if SOURCE_ROOT.name == "1-app-source-code" else SOURCE_ROOT
)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 30

load_dotenv(REPOSITORY_ROOT / ".env", override=True)


def image_data_uri(path, media_type):
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


logo_data_uri = image_data_uri(ASSET_DIR / "ghana-evisa-logo.png", "image/png")
hero_data_uri = image_data_uri(ASSET_DIR / "ghana-evisa-hero.jpg", "image/jpeg")


def verify_password(password, encoded_hash):
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value)
        expected_digest = base64.urlsafe_b64decode(digest_value)
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected_digest),
        )
    except (binascii.Error, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def credentials_are_valid(username, password):
    configured_username = os.getenv("FOSU_DASHBOARD_USERNAME", "")
    configured_password_hash = os.getenv("FOSU_DASHBOARD_PASSWORD_HASH", "")
    username_matches = hmac.compare_digest(username, configured_username)
    password_matches = verify_password(password, configured_password_hash)
    return username_matches and password_matches

st.set_page_config(
    page_title="Project Fosu | Command Center",
    page_icon="F",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');

    :root {
        --canvas: #f4efe3;
        --surface: #fffdf7;
        --ink: #18352a;
        --muted: #6f786f;
        --teal: #286b48;
        --teal-dark: #174a32;
        --teal-soft: #e4eee6;
        --gold: #c49a32;
        --danger: #b94c4c;
        --border: #ded8c9;
    }

    html, body, [class*="css"] { font-family: "DM Sans", sans-serif; }
    h1, h2, h3 { font-family: "Manrope", sans-serif !important; letter-spacing: 0 !important; }
    .stApp { background: var(--canvas); color: var(--ink); }
    .block-container { max-width: 1560px; padding: 2rem 2.4rem 3rem; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
    }
    [data-testid="stSidebar"] .block-container { padding: 1.8rem 1.35rem; }
    [data-testid="stSidebar"] hr { border-color: var(--border); }

    .official-lockup { display: block; height: auto; margin: .1rem 0 1rem; max-width: 100%; width: 238px; }
    .brand { border-top: 1px solid var(--border); margin: 0 0 1.55rem; padding-top: .85rem; }
    .brand-name { color: var(--ink); font-family: "Manrope", sans-serif; font-size: .95rem; font-weight: 800; line-height: 1.05; }
    .brand-meta { color: var(--muted); font-size: .68rem; font-weight: 600; margin-top: .3rem; }
    .sidebar-label {
        color: #8b9188; font-size: .68rem; font-weight: 700;
        letter-spacing: .09em; margin: .9rem 0 .25rem; text-transform: uppercase;
    }
    .system-card {
        border: 1px solid var(--border); border-radius: 8px; padding: .95rem 1rem;
        background: #faf7ee; margin: 1.1rem 0 .4rem;
    }
    .system-row { display: flex; justify-content: space-between; align-items: center; }
    .system-title { color: var(--ink); font-size: .82rem; font-weight: 700; }
    .system-copy { color: var(--muted); font-size: .72rem; margin-top: .35rem; line-height: 1.45; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 4px var(--teal-soft); }

    .page-header {
        align-items: flex-start; background: #174a32; border-radius: 8px;
        display: flex; justify-content: space-between; gap: 2rem; margin-bottom: 1.4rem;
        min-height: 184px; overflow: hidden; padding: 1.65rem 1.75rem; position: relative;
    }
    .page-header::after {
        background: linear-gradient(90deg, rgba(17, 61, 40, .95), rgba(30, 91, 59, .74) 58%, rgba(17, 61, 40, .32));
        content: ""; inset: 0; position: absolute; z-index: 1;
    }
    .page-header::before {
        background: linear-gradient(90deg, #b94c4c 0 33.33%, #c49a32 33.33% 66.66%, #286b48 66.66%);
        content: ""; height: 4px; left: 0; position: absolute; right: 0; top: 0; z-index: 3;
    }
    .hero-background { height: 100%; inset: 0; object-fit: cover; object-position: center 43%; position: absolute; width: 100%; z-index: 0; }
    .page-header > div { position: relative; z-index: 2; }
    .eyebrow { color: #e5c66b; font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    .page-title { color: #ffffff; font-size: 1.8rem; font-weight: 800; margin: .25rem 0 .35rem; }
    .page-subtitle { color: rgba(255, 255, 255, .82); font-size: .88rem; }
    .prototype-label { color: rgba(255, 255, 255, .65); font-size: .68rem; font-weight: 600; margin-top: .75rem; }
    .live-pill {
        align-items: center; background: rgba(255, 255, 255, .94); border: 1px solid rgba(255, 255, 255, .55);
        border-radius: 8px; color: var(--ink); display: flex; font-size: .76rem;
        font-weight: 700; gap: .55rem; padding: .65rem .85rem; white-space: nowrap;
    }
    .live-pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--teal); }

    [data-testid="stMetric"] {
        background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        min-height: 124px; padding: 1.15rem 1.2rem;
        box-shadow: 0 7px 24px rgba(24, 53, 42, .055);
    }
    [data-testid="stMetricLabel"] { color: var(--muted); font-size: .75rem; font-weight: 700; }
    [data-testid="stMetricValue"] { color: var(--ink); font-family: "Manrope", sans-serif; font-size: 1.75rem; font-weight: 800; }
    [data-testid="stMetricDelta"] { font-size: .72rem; font-weight: 700; }

    [data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 1.8rem; border-bottom: 1px solid var(--border); }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        background: transparent; border: 0; color: var(--muted); font-size: .82rem;
        font-weight: 700; padding: .9rem .15rem; width: auto;
    }
    [data-testid="stTabs"] [aria-selected="true"] { color: var(--teal-dark); }
    [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--teal); }

    .section-heading { color: var(--ink); font-family: "Manrope", sans-serif; font-size: 1rem; font-weight: 800; margin: 1.25rem 0 .15rem; }
    .section-copy { color: var(--muted); font-size: .76rem; margin-bottom: .9rem; }
    .map-legend { display: flex; flex-wrap: wrap; gap: 1rem; margin: .2rem 0 .7rem; }
    .legend-item { color: var(--muted); font-size: .72rem; font-weight: 600; }
    .legend-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .35rem; }
    .legend-teal { background: var(--teal); }
    .legend-red { background: var(--danger); }
    .legend-amber { background: var(--gold); }

    [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
    [data-testid="stAlert"] { border-radius: 8px; }
    .stButton > button {
        border: 1px solid var(--border); border-radius: 8px; color: var(--ink);
        font-weight: 700; min-height: 2.65rem; width: 100%;
    }
    .stButton > button:hover { border-color: var(--teal); color: var(--teal-dark); }
    .stSelectbox label { color: var(--ink) !important; font-size: .76rem !important; font-weight: 700 !important; }
    div[data-baseweb="select"] > div { border-color: var(--border); border-radius: 8px; }
    iframe { border-radius: 8px; }
    footer { visibility: hidden; }
    .asset-credit { color: #8b9188; font-size: .62rem; line-height: 1.45; margin-top: 1rem; }
    .login-background { height: 100vh; inset: 0; object-fit: cover; object-position: center 42%; position: fixed; width: 100vw; z-index: 0; }
    .login-backdrop { background: linear-gradient(90deg, rgba(10, 15, 14, .91), rgba(18, 25, 23, .74) 58%, rgba(10, 15, 14, .58)); inset: 0; position: fixed; z-index: 0; }
    .login-hero { min-height: 165px; margin: 1.5rem 0 .75rem; padding: 2rem 0; position: relative; }
    .login-identity { position: relative; z-index: 1; }
    .login-kicker { color: #e1b84b; font-size: .7rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    .login-title { color: #fffaf0; font-family: "Manrope", sans-serif; font-size: 1.65rem; font-weight: 800; margin-top: .3rem; }
    .login-copy { color: #b9c0bd; font-size: .8rem; margin-top: .35rem; }
    .login-rule { background: #e1b84b; height: 4px; left: 0; position: absolute; right: 0; top: 0; z-index: 2; }
    .login-heading { color: #fffaf0; font-family: "Manrope", sans-serif; font-size: 1.15rem; font-weight: 800; margin-top: .4rem; }
    .login-caption { color: #9fa9a5; font-size: .76rem; margin: .25rem 0 1rem; }

    @media (max-width: 760px) {
        .block-container { padding: 1.2rem 1rem 2rem; }
        .page-header { display: block; }
        .live-pill { margin-top: 1rem; width: fit-content; }
        .page-title { font-size: 1.45rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def require_authentication():
    if st.session_state.get("authenticated"):
        return

    configured_username = os.getenv("FOSU_DASHBOARD_USERNAME")
    configured_password_hash = os.getenv("FOSU_DASHBOARD_PASSWORD_HASH")
    if not configured_username or not configured_password_hash:
        st.error("Dashboard authentication is not configured. Set the FOSU dashboard credentials.")
        st.stop()

    st.markdown(
        """
        <style>
        .stApp { background: #151b1a; color: #fffaf0; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stMain"] { position: relative; z-index: 1; }
        [data-testid="stMainBlockContainer"] { max-width: 1180px; position: relative; z-index: 1; }
        [data-testid="stForm"] { border: 0; padding: 0; }
        [data-testid="stTextInput"] label p { color: #d8dedb !important; }
        [data-testid="stTextInput"] input {
            background: #222a28; border-color: #44504c; color: #fffaf0;
        }
        [data-testid="stTextInput"] input:focus { border-color: #e1b84b; box-shadow: 0 0 0 1px #e1b84b; }
        [data-testid="stTextInput"] button { color: #c5ccc9; }
        [data-testid="stFormSubmitButton"] button {
            background: #e1b84b; border-color: #e1b84b; color: #18201e;
        }
        [data-testid="stFormSubmitButton"] button:hover {
            background: #f0cb67; border-color: #f0cb67; color: #18201e;
        }
        [data-testid="stCaptionContainer"] { color: #7f8b86; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <img class="login-background" src="{hero_data_uri}" alt="Ghana landscape">
        <div class="login-backdrop"></div>
        <div class="login-hero">
            <div class="login-rule"></div>
            <div class="login-identity">
                <div class="login-kicker">Restricted operational system</div>
                <div class="login-title">Project Fosu Command Center</div>
                <div class="login-copy">Authorized personnel access only</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, login_column, _ = st.columns([1, 1.1, 1])
    with login_column:
        st.markdown('<div class="login-heading">Secure sign in</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-caption">Enter your assigned command-center credentials.</div>',
            unsafe_allow_html=True,
        )
        lockout_remaining = max(
            0, int(st.session_state.get("login_locked_until", 0) - time.time())
        )
        with st.form("dashboard_login", clear_on_submit=False):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input(
                "Password", type="password", autocomplete="current-password"
            )
            submitted = st.form_submit_button(
                "Sign in", width="stretch", disabled=lockout_remaining > 0
            )

        if lockout_remaining > 0:
            st.error(f"Too many failed attempts. Try again in {lockout_remaining} seconds.")
        elif submitted:
            if credentials_are_valid(username.strip(), password):
                st.session_state["authenticated"] = True
                st.session_state["failed_login_attempts"] = 0
                st.rerun()
            else:
                failures = st.session_state.get("failed_login_attempts", 0) + 1
                st.session_state["failed_login_attempts"] = failures
                if failures >= MAX_LOGIN_ATTEMPTS:
                    st.session_state["login_locked_until"] = time.time() + LOCKOUT_SECONDS
                    st.session_state["failed_login_attempts"] = 0
                    st.error(f"Too many failed attempts. Access locked for {LOCKOUT_SECONDS} seconds.")
                else:
                    remaining_attempts = MAX_LOGIN_ATTEMPTS - failures
                    st.error(f"Invalid username or password. {remaining_attempts} attempts remaining.")
        st.caption("Project Fosu operational prototype · Ghana Immigration visual assets")
    st.stop()


require_authentication()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_json(path, params=None):
    response = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.markdown(
        f"""
        <img class="official-lockup" src="{logo_data_uri}" alt="Ministry of Foreign Affairs and Ghana Immigration Service">
        <div class="brand">
            <div class="brand-name">PROJECT FOSU</div>
            <div class="brand-meta">WHOLE-BORDER INTELLIGENCE PROTOTYPE</div>
        </div>
        <div class="sidebar-label">Mission controls</div>
        """,
        unsafe_allow_html=True,
    )
    time_window = st.selectbox(
        "Monitoring window",
        options=[24, 48, 72, 168],
        index=1,
        format_func=lambda hours: "7 days" if hours == 168 else f"Last {hours} hours",
    )
    country_filter = st.selectbox(
        "Border sector",
        ["All sectors", "Togo", "Burkina Faso", "Côte d'Ivoire"],
    )
    type_filter = st.selectbox(
        "Event classification",
        ["All events", "Approved", "Unapproved route"],
    )
    st.markdown(
        """
        <div class="system-card">
            <div class="system-row"><span class="system-title">System status</span><span class="status-dot"></span></div>
            <div class="system-copy">Border geometry loaded<br>15-second data refresh cycle</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Refresh intelligence", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    if st.button("Sign out", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.markdown(
        """
        <div class="asset-credit">Institutional logo and hero photography sourced from the public Ghana eVisa portal. Project Fosu is an operational prototype and is not the eVisa service.</div>
        """,
        unsafe_allow_html=True,
    )

try:
    checkpoints = fetch_json("/checkpoints")
    crossings = fetch_json("/crossings", params={"hours": time_window})
    daily_stats = fetch_json("/stats/daily", params={"days": max(7, time_window // 24)})
    hotspots = fetch_json(
        "/stats/hotspots", params={"hours": time_window, "min_events": 2}
    )
    geometry = fetch_json("/border-geometry")
except requests.RequestException as exc:
    st.error("The command center cannot reach the Project Fosu API.")
    st.code(
        "uvicorn --app-dir 1-app-source-code app.main:app --reload --port 8000",
        language="bash",
    )
    st.caption(f"Connection detail: {exc}")
    st.stop()

checkpoint_df = pd.DataFrame(checkpoints)
crossing_df = pd.DataFrame(crossings)
stats_df = pd.DataFrame(daily_stats)
hotspot_df = pd.DataFrame(hotspots)

if not crossing_df.empty:
    if country_filter != "All sectors":
        crossing_df = crossing_df[crossing_df["neighbor_country"] == country_filter]
    if type_filter != "All events":
        selected_type = "approved" if type_filter == "Approved" else "unapproved_route"
        crossing_df = crossing_df[crossing_df["crossing_type"] == selected_type]

if not hotspot_df.empty and country_filter != "All sectors":
    hotspot_df = hotspot_df[hotspot_df["neighbor_country"] == country_filter]

total_headcount = int(crossing_df["estimated_headcount"].sum()) if not crossing_df.empty else 0
unapproved_headcount = (
    int(
        crossing_df.loc[
            crossing_df["crossing_type"] == "unapproved_route", "estimated_headcount"
        ].sum()
    )
    if not crossing_df.empty
    else 0
)
approved_headcount = total_headcount - unapproved_headcount
approved_rate = round((approved_headcount / total_headcount) * 100) if total_headcount else 0
average_confidence = (
    crossing_df["confidence_score"].mean() * 100 if not crossing_df.empty else 0
)
updated_at = datetime.now().astimezone().strftime("%H:%M %Z")

st.markdown(
    f"""
    <div class="page-header">
        <img class="hero-background" src="{hero_data_uri}" alt="Ghana landscape">
        <div>
            <div class="eyebrow">National operations / Live overview</div>
            <div class="page-title">Whole-Border Command Center</div>
            <div class="page-subtitle">Operational awareness across Ghana's monitored land-border corridor</div>
            <div class="prototype-label">PROJECT FOSU · OPERATIONAL PROTOTYPE</div>
        </div>
        <div class="live-pill"><span class="live-pulse"></span>Live intelligence &nbsp;·&nbsp; {updated_at}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

metric_columns = st.columns(4)
metric_columns[0].metric(
    "Estimated crossings",
    f"{total_headcount:,}",
    f"{len(crossing_df):,} logged events",
    delta_color="off",
)
metric_columns[1].metric(
    "Unapproved movement",
    f"{unapproved_headcount:,}",
    f"{(unapproved_headcount / total_headcount * 100):.1f}% of headcount"
    if total_headcount
    else "No movement recorded",
    delta_color="inverse" if unapproved_headcount else "off",
)
metric_columns[2].metric(
    "Active hotspot clusters",
    f"{len(hotspot_df):,}",
    "Requires attention" if len(hotspot_df) else "No active clusters",
    delta_color="inverse" if len(hotspot_df) else "off",
)
metric_columns[3].metric(
    "Approved passage rate",
    f"{approved_rate}%",
    f"{average_confidence:.0f}% avg. confidence",
    delta_color="off",
)

overview_tab, analytics_tab, events_tab = st.tabs(
    ["Operational overview", "Movement analytics", "Event registry"]
)

with overview_tab:
    st.markdown('<div class="section-heading">Border activity map</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Live event density, official entry points, and emerging informal routes</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="map-legend">
            <span class="legend-item"><span class="legend-swatch legend-teal"></span>Official checkpoint</span>
            <span class="legend-item"><span class="legend-swatch legend-red"></span>Active hotspot</span>
            <span class="legend-item"><span class="legend-swatch legend-amber"></span>Movement density</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    border_map = folium.Map(
        location=[7.9465, -1.0232],
        zoom_start=7,
        tiles="CartoDB positron",
        control_scale=True,
    )
    for feature in geometry["corridor"]["features"]:
        folium.GeoJson(
            feature,
            style_function=lambda _: {
                "color": "#286b48",
                "weight": 0,
                "fillColor": "#286b48",
                "fillOpacity": 0.08,
            },
            name="Monitored corridor",
        ).add_to(border_map)
    for feature in geometry["lines"]["features"]:
        neighbor = feature["properties"]["neighbor"]
        length = feature["properties"]["length_km"]
        folium.GeoJson(
            feature,
            style_function=lambda _: {
                "color": "#596b5f",
                "weight": 2,
                "dashArray": "5,5",
            },
            tooltip=f"{neighbor} border · approximately {length} km",
            name="National border",
        ).add_to(border_map)

    for _, checkpoint in checkpoint_df.iterrows():
        folium.CircleMarker(
            location=[checkpoint["latitude"], checkpoint["longitude"]],
            radius=7,
            color="#ffffff",
            weight=2,
            fill=True,
            fill_color="#286b48",
            fill_opacity=1,
            tooltip=f"{checkpoint['name']} · Official checkpoint",
            popup=(
                f"<b>{checkpoint['name']}</b><br>Official port of entry<br>"
                f"Sector: {checkpoint['neighboring_country']}"
            ),
        ).add_to(border_map)

    if not crossing_df.empty:
        heat_data = crossing_df[
            ["latitude", "longitude", "estimated_headcount"]
        ].values.tolist()
        HeatMap(
            heat_data,
            radius=20,
            blur=24,
            min_opacity=0.22,
            gradient={0.25: "#e5c66b", 0.55: "#c49a32", 0.8: "#b94c4c"},
            name="Crossing density",
        ).add_to(border_map)

    for _, hotspot in hotspot_df.iterrows():
        distance = hotspot["distance_to_nearest_checkpoint_m"]
        distance_label = f"{distance / 1000:.1f} km" if pd.notna(distance) else "Unknown"
        folium.CircleMarker(
            location=[hotspot["latitude"], hotspot["longitude"]],
            radius=8 + min(hotspot["total_headcount"], 30) * 0.35,
            color="#ffffff",
            weight=2,
            fill=True,
            fill_color="#b94c4c",
            fill_opacity=0.82,
            tooltip=f"Hotspot · {hotspot['total_headcount']} estimated crossings",
            popup=folium.Popup(
                f"<b>Emerging route</b><br>Sector: {hotspot['neighbor_country']}<br>"
                f"Headcount: {hotspot['total_headcount']}<br>Events: {hotspot['event_count']}<br>"
                f"Nearest checkpoint: {distance_label}",
                max_width=260,
            ),
        ).add_to(border_map)

    folium.LayerControl(position="topright", collapsed=True).add_to(border_map)
    st_folium(border_map, use_container_width=True, height=560, returned_objects=[])

    st.markdown('<div class="section-heading">Priority hotspots</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Highest-volume unapproved movement clusters in the selected window</div>',
        unsafe_allow_html=True,
    )
    if hotspot_df.empty:
        st.info("No hotspot clusters match the current filters.")
    else:
        priority_hotspots = hotspot_df[
            [
                "neighbor_country",
                "grid_cell",
                "total_headcount",
                "event_count",
                "distance_to_nearest_checkpoint_m",
            ]
        ].head(8)
        st.dataframe(
            priority_hotspots,
            use_container_width=True,
            hide_index=True,
            column_config={
                "neighbor_country": st.column_config.TextColumn("Border sector"),
                "grid_cell": st.column_config.TextColumn("Grid reference"),
                "total_headcount": st.column_config.NumberColumn("Headcount", format="%d"),
                "event_count": st.column_config.NumberColumn("Events", format="%d"),
                "distance_to_nearest_checkpoint_m": st.column_config.NumberColumn(
                    "Checkpoint distance", format="%.0f m"
                ),
            },
        )

with analytics_tab:
    st.markdown('<div class="section-heading">Movement trend</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Daily estimated headcount by route classification</div>',
        unsafe_allow_html=True,
    )
    if stats_df.empty:
        st.info("No movement trend is available yet. Generate sensor data to begin analysis.")
    else:
        chart_data = stats_df.copy()
        chart_data["crossing_type"] = chart_data["crossing_type"].replace(
            {"approved": "Approved", "unapproved_route": "Unapproved route"}
        )
        chart_data = chart_data.pivot_table(
            index="day",
            columns="crossing_type",
            values="total_headcount",
            fill_value=0,
        )
        chart_colors = [
            "#286b48" if column == "Approved" else "#b94c4c"
            for column in chart_data.columns
        ]
        st.bar_chart(
            chart_data,
            color=chart_colors,
            height=390,
            use_container_width=True,
        )

    detail_left, detail_right = st.columns(2)
    with detail_left:
        st.markdown('<div class="section-heading">Activity by sector</div>', unsafe_allow_html=True)
        if crossing_df.empty:
            st.info("No sector activity matches the current filters.")
        else:
            sector_data = (
                crossing_df.groupby("neighbor_country", dropna=False)["estimated_headcount"]
                .sum()
                .sort_values(ascending=False)
            )
            st.bar_chart(sector_data, color="#286b48", height=280)
    with detail_right:
        st.markdown('<div class="section-heading">Reports by source</div>', unsafe_allow_html=True)
        if crossing_df.empty:
            st.info("No source data matches the current filters.")
        else:
            source_data = crossing_df["source"].fillna("unknown").value_counts()
            st.bar_chart(source_data, color="#c49a32", height=280)

with events_tab:
    st.markdown('<div class="section-heading">Event registry</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Most recent sensor, camera, guard, and manual reports</div>',
        unsafe_allow_html=True,
    )
    if crossing_df.empty:
        st.info("No crossing events match the current filters.")
    else:
        event_columns = [
            "timestamp",
            "neighbor_country",
            "crossing_type",
            "estimated_headcount",
            "source",
            "confidence_score",
            "nearest_checkpoint_code",
            "distance_to_checkpoint_m",
        ]
        event_log = crossing_df[event_columns].copy()
        event_log["timestamp"] = pd.to_datetime(event_log["timestamp"])
        event_log["crossing_type"] = event_log["crossing_type"].replace(
            {"approved": "Approved", "unapproved_route": "Unapproved route"}
        )
        st.dataframe(
            event_log,
            use_container_width=True,
            hide_index=True,
            height=560,
            column_config={
                "timestamp": st.column_config.DatetimeColumn("Reported at", format="MMM D, HH:mm"),
                "neighbor_country": st.column_config.TextColumn("Border sector"),
                "crossing_type": st.column_config.TextColumn("Classification"),
                "estimated_headcount": st.column_config.NumberColumn("Headcount", format="%d"),
                "source": st.column_config.TextColumn("Source"),
                "confidence_score": st.column_config.ProgressColumn(
                    "Confidence", min_value=0, max_value=1, format="%.0f%%"
                ),
                "nearest_checkpoint_code": st.column_config.TextColumn("Nearest post"),
                "distance_to_checkpoint_m": st.column_config.NumberColumn(
                    "Distance", format="%.0f m"
                ),
            },
        )

# Project-Fosu-Smart-Border-Ingress-Alert-System-MVP-
A prototype border-crossing logging, mapping, and threshold-alert system that covers **the whole border**, not just a handful of named checkpoints.

## Run locally

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --reload --port 8000
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Open `http://localhost:8501`. The dashboard is protected by a session login and does not request operational API data until authentication succeeds.

## Replace mock sensor with YOLO detection

You can feed live detections from a camera/video stream into the same existing ingestion logic (no backend changes required):

```bash
source .venv/bin/activate
pip install -r requirements.txt
python 1-app-source-code/scripts/yolo_sensor.py \
	--source 0 \
	--camera-lat 6.1219 \
	--camera-lon 1.1974 \
	--post-interval 5 \
	--display
```

Notes:

- `--source` can be webcam index (`0`), video file path, or RTSP URL.
- The script sends the same payload shape used by `mock_sensor.py` to `/ingest`.
- Keep `uvicorn` running first so YOLO events can be recorded and visualized on the dashboard.

### Switch sensors during a demonstration

Keep the API and dashboard running in separate terminals:

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --host 127.0.0.1 --port 8000
```

```bash
source .venv/bin/activate
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Run only one event producer at a time. Start with simulated events:

```bash
source .venv/bin/activate
python3 1-app-source-code/scripts/mock_sensor.py --interval 5
```

Stop the mock sensor with `Ctrl+C`. For a short batch instead, use:

```bash
python3 1-app-source-code/scripts/mock_sensor.py --once --n 20
```

Then start the camera sensor:

```bash
source .venv/bin/activate
python3 1-app-source-code/scripts/yolo_sensor.py \
	--api-url http://127.0.0.1:8000/ingest \
	--model yolov8n.pt \
	--source 0 \
	--classes person \
	--low-light \
	--infrared \
	--inference-confidence 0.20 \
	--min-confidence 0.20 \
	--imgsz 640 \
	--display
```

Stop YOLO with `q` in the preview window or `Ctrl+C` in its terminal before
switching back to `mock_sensor.py`. Both sensors send events to the same
`/ingest` endpoint, so new detections appear in the dashboard automatically.

### Lightweight infrared night detection

Use an IR-capable USB or RTSP camera with the lightweight YOLO model. The
`--infrared` option enhances monochrome IR frames and converts them to the
three-channel format expected by YOLO:

```bash
python 1-app-source-code/scripts/yolo_sensor.py \
	--model yolov8n.pt \
	--source 0 \
	--classes person \
	--infrared \
	--inference-confidence 0.20 \
	--min-confidence 0.20 \
	--imgsz 640 \
	--display
```

For small or distant people, use `yolov8s.pt` and `--imgsz 960`, but expect
slower CPU inference. A thermal camera requires a model trained or fine-tuned
on thermal imagery; ordinary YOLO weights may not detect thermal silhouettes
reliably.

### Multi-camera mode (one process)

Use the JSON camera list (one worker thread per enabled camera):

```bash
python 1-app-source-code/scripts/yolo_sensor.py \
	--config 1-app-source-code/scripts/cameras.example.json
```

Each camera entry can define its own `source`, geolocation, confidence threshold,
post interval, and optional calibration file.

### Zone calibration for better geolocation

To map pixel regions to more realistic geo locations, provide a calibration file
for each camera (example: `1-app-source-code/scripts/calibration.example.json`).

Calibration format:

```json
{
	"frame_width": 1920,
	"frame_height": 1080,
	"zones": [
		{
			"name": "zone-name",
			"pixel": [x1, y1, x2, y2],
			"geo": [min_lat, min_lon, max_lat, max_lon]
		}
	]
}
```

If a detection center falls inside a zone, coordinates are projected using that
zone mapping. If no zone matches, the script falls back to lat/lon span mapping.

## Run with Docker

Build and start the API and dashboard with Compose:

```bash
docker compose up --build -d
```

Compose loads dashboard credentials from `.env`, publishes ports `8000` and `8501`, and persists SQLite data in the `fosu-data` named volume.

Compose also starts the `yolo-sensor` service, which reads camera streams from:

- `1-app-source-code/scripts/cameras.example.json`

Update that file with your real RTSP/video sources and camera coordinates.

View logs or stop the application with:

```bash
docker compose logs -f
docker compose down
```

Open the dashboard at `http://localhost:8501` or the API documentation at `http://localhost:8000/docs`.

## Dashboard credentials

Credentials are read from the ignored `.env` file as `FOSU_DASHBOARD_USERNAME` and a one-way `FOSU_DASHBOARD_PASSWORD_HASH`. Rotate them with:

```bash
python 1-app-source-code/scripts/set_dashboard_password.py --username fosu.admin
```

The command prompts for the password without displaying it, writes a salted scrypt hash, and never stores the plain-text password. Reload the login page after changing credentials. In deployment, provide the same environment variables through the hosting platform's secret manager instead of committing `.env`.

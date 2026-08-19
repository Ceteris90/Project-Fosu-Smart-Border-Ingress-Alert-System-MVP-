"""
YOLO-powered sensor ingestion for Project Fosu.

Features:
- Single-camera mode (CLI flags).
- Multi-camera mode from a JSON config file (one process, many worker threads).
- Optional zone calibration: pixel rectangles mapped to geo rectangles for
  more realistic coordinate projection.

All events still use the existing /ingest payload format so backend and
dashboard logic remain unchanged.
"""

import argparse
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy as np
import requests

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "opencv-python is required. Install dependencies from requirements.txt."
    ) from exc

try:
    from ultralytics import YOLO
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "ultralytics is required. Install dependencies from requirements.txt."
    ) from exc


DEFAULT_API_URL = "http://localhost:8000/ingest"


@dataclass
class CameraConfig:
    camera_id: str
    source: Union[int, str]
    camera_lat: float
    camera_lon: float
    lat_span: float
    lon_span: float
    post_interval: float
    min_confidence: float
    source_label: str
    calibration_file: Optional[str] = None
    enabled: bool = True


def parse_source(value: Union[str, int]) -> Union[int, str]:
    """Allow webcam index (e.g., 0) or a video/RTSP path."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def load_zone_calibration(calibration_file: Optional[str]) -> Optional[dict]:
    if not calibration_file:
        return None
    path = Path(calibration_file)
    if not path.exists():
        print(f"WARN calibration file not found: {calibration_file}")
        return None

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if "zones" not in data or not isinstance(data["zones"], list):
        print(f"WARN invalid calibration format: {calibration_file}")
        return None
    return data


def point_in_rect(x: float, y: float, rect: List[float]) -> bool:
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2


def map_center_by_zone(
    center_x: float,
    center_y: float,
    frame_width: int,
    frame_height: int,
    calibration: Optional[dict],
) -> Optional[Tuple[float, float]]:
    if not calibration:
        return None

    base_w = float(calibration.get("frame_width") or frame_width)
    base_h = float(calibration.get("frame_height") or frame_height)
    sx = frame_width / base_w if base_w else 1.0
    sy = frame_height / base_h if base_h else 1.0

    for zone in calibration.get("zones", []):
        pixel_rect = zone.get("pixel")
        geo_rect = zone.get("geo")
        if not pixel_rect or not geo_rect or len(pixel_rect) != 4 or len(geo_rect) != 4:
            continue

        x1, y1, x2, y2 = [float(v) for v in pixel_rect]
        scaled_rect = [x1 * sx, y1 * sy, x2 * sx, y2 * sy]
        if not point_in_rect(center_x, center_y, scaled_rect):
            continue

        min_lat, min_lon, max_lat, max_lon = [float(v) for v in geo_rect]
        width = max(1e-9, scaled_rect[2] - scaled_rect[0])
        height = max(1e-9, scaled_rect[3] - scaled_rect[1])
        nx = (center_x - scaled_rect[0]) / width
        ny = (center_y - scaled_rect[1]) / height

        lat = max_lat - ny * (max_lat - min_lat)
        lon = min_lon + nx * (max_lon - min_lon)
        return lat, lon

    return None


def fallback_position(
    center_x: float,
    center_y: float,
    frame_width: int,
    frame_height: int,
    camera_lat: float,
    camera_lon: float,
    lat_span: float,
    lon_span: float,
) -> Tuple[float, float]:
    if lat_span == 0 and lon_span == 0:
        return camera_lat, camera_lon

    norm_x = clamp((center_x / frame_width) - 0.5, -0.5, 0.5)
    norm_y = clamp((center_y / frame_height) - 0.5, -0.5, 0.5)
    lat = camera_lat + (-norm_y * lat_span)
    lon = camera_lon + (norm_x * lon_span)
    return lat, lon


def approximate_event_position(
    detections: List[Tuple[float, float]],
    frame_width: int,
    frame_height: int,
    camera_cfg: CameraConfig,
    calibration: Optional[dict],
) -> Tuple[float, float]:
    if not detections:
        return camera_cfg.camera_lat, camera_cfg.camera_lon

    mapped_points: List[Tuple[float, float]] = []
    for center_x, center_y in detections:
        zone_geo = map_center_by_zone(center_x, center_y, frame_width, frame_height, calibration)
        if zone_geo is not None:
            mapped_points.append(zone_geo)
        else:
            mapped_points.append(
                fallback_position(
                    center_x,
                    center_y,
                    frame_width,
                    frame_height,
                    camera_cfg.camera_lat,
                    camera_cfg.camera_lon,
                    camera_cfg.lat_span,
                    camera_cfg.lon_span,
                )
            )

    lat = sum(p[0] for p in mapped_points) / len(mapped_points)
    lon = sum(p[1] for p in mapped_points) / len(mapped_points)
    return lat, lon


def post_event(
    api_url: str,
    latitude: float,
    longitude: float,
    estimated_headcount: int,
    confidence_score: float,
    source: str,
    timeout: float,
    camera_id: str,
) -> None:
    payload = {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "estimated_headcount": estimated_headcount,
        "confidence_score": round(confidence_score, 2),
        "source": source,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        print(
            "OK "
            f"[{camera_id}] "
            f"headcount={estimated_headcount:2d} "
            f"conf={confidence_score:.2f} "
            f"({latitude:.5f},{longitude:.5f}) -> "
            f"{data.get('crossing_type')} "
            f"near {data.get('nearest_checkpoint_code')}"
        )
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = exc.response.text
        print(f"ERR [{camera_id}] failed posting event: {exc} {detail}")


def resolve_class_ids(model: YOLO, class_names: str) -> List[int]:
    names = model.names
    name_to_id = {str(label).lower(): int(class_id) for class_id, label in names.items()}
    requested = [name.strip().lower() for name in class_names.split(",") if name.strip()]
    unknown = [name for name in requested if name not in name_to_id]
    if unknown:
        available = ", ".join(sorted(name_to_id))
        raise SystemExit(f"Unknown YOLO class(es): {', '.join(unknown)}. Available: {available}")
    return [name_to_id[name] for name in requested]


def enhance_low_light(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, channels_a, channels_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_lightness = clahe.apply(lightness)
    enhanced = cv2.cvtColor(
        cv2.merge((enhanced_lightness, channels_a, channels_b)), cv2.COLOR_LAB2BGR
    )
    gamma = 1.8
    lookup = ((np.arange(256) / 255.0) ** (1.0 / gamma) * 255).astype("uint8")
    return cv2.LUT(enhanced, lookup)


def enhance_infrared(frame):
    grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(grayscale)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def run_camera_worker(args: argparse.Namespace, camera_cfg: CameraConfig, stop_event: threading.Event) -> None:
    calibration = load_zone_calibration(camera_cfg.calibration_file)
    model = YOLO(args.model)
    target_class_ids = resolve_class_ids(model, args.classes)
    class_labels = {class_id: str(model.names[class_id]) for class_id in target_class_ids}
    last_post_ts = 0.0

    print(
        f"Starting camera worker [{camera_cfg.camera_id}] "
        f"source={camera_cfg.source} post_interval={camera_cfg.post_interval}s"
    )

    while not stop_event.is_set():
        cap = cv2.VideoCapture(camera_cfg.source)
        if not cap.isOpened():
            print(
                f"WARN [{camera_cfg.camera_id}] unable to open source={camera_cfg.source}; "
                f"retrying in {args.reconnect_delay}s"
            )
            cap.release()
            stop_event.wait(args.reconnect_delay)
            continue

        try:
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    print(f"WARN [{camera_cfg.camera_id}] frame read failed; reconnecting source")
                    break

                processed_frame = frame
                if args.infrared:
                    processed_frame = enhance_infrared(processed_frame)
                if args.low_light:
                    processed_frame = enhance_low_light(processed_frame)
                result = model(
                    processed_frame,
                    classes=target_class_ids,
                    conf=args.inference_confidence,
                    imgsz=args.imgsz,
                    verbose=False,
                )[0]
                boxes = result.boxes
                centers: List[Tuple[float, float]] = []
                confidences: List[float] = []

                if boxes is not None:
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        if conf < camera_cfg.min_confidence:
                            continue

                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        center_x = (x1 + x2) / 2.0
                        center_y = (y1 + y2) / 2.0
                        centers.append((center_x, center_y))
                        confidences.append(conf)

                        if args.display:
                            cv2.rectangle(
                                processed_frame,
                                (int(x1), int(y1)),
                                (int(x2), int(y2)),
                                (0, 200, 0),
                                2,
                            )
                            cv2.putText(
                                processed_frame,
                                f"{class_labels[cls_id]} {conf:.2f}",
                                (int(x1), max(20, int(y1) - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (0, 200, 0),
                                1,
                                cv2.LINE_AA,
                            )

                now = time.time()
                if centers and (now - last_post_ts) >= camera_cfg.post_interval:
                    height, width = frame.shape[:2]
                    lat, lon = approximate_event_position(
                        detections=centers,
                        frame_width=width,
                        frame_height=height,
                        camera_cfg=camera_cfg,
                        calibration=calibration,
                    )
                    avg_conf = sum(confidences) / len(confidences)
                    post_event(
                        api_url=args.api_url,
                        latitude=lat,
                        longitude=lon,
                        estimated_headcount=len(centers),
                        confidence_score=avg_conf,
                        source=camera_cfg.source_label,
                        timeout=args.request_timeout,
                        camera_id=camera_cfg.camera_id,
                    )
                    last_post_ts = now

                if args.display:
                    cv2.putText(
                        processed_frame,
                        f"{camera_cfg.camera_id} detections={len(centers)}",
                        (16, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 0),
                        2,
                        cv2.LINE_AA,
                    )
                    window_name = f"Project Fosu YOLO Sensor - {camera_cfg.camera_id}"
                    cv2.imshow(window_name, processed_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        stop_event.set()
                        break
        finally:
            cap.release()

    if args.display:
        cv2.destroyAllWindows()


def load_camera_configs(args: argparse.Namespace) -> List[CameraConfig]:
    if not args.config:
        return [
            CameraConfig(
                camera_id=args.camera_id,
                source=args.source,
                camera_lat=args.camera_lat,
                camera_lon=args.camera_lon,
                lat_span=args.lat_span,
                lon_span=args.lon_span,
                post_interval=args.post_interval,
                min_confidence=args.min_confidence,
                source_label=args.source_label,
                calibration_file=args.calibration_file,
                enabled=True,
            )
        ]

    with open(args.config, "r", encoding="utf-8") as handle:
        config_data = json.load(handle)

    cameras_raw = config_data.get("cameras", [])
    if not cameras_raw:
        raise SystemExit(f"No camera entries found in config: {args.config}")

    cameras: List[CameraConfig] = []
    for idx, item in enumerate(cameras_raw):
        enabled = bool(item.get("enabled", True))
        if not enabled:
            continue

        camera_id = str(item.get("camera_id") or f"cam-{idx + 1}")
        source = parse_source(item.get("source", 0))
        camera_lat = float(item.get("camera_lat"))
        camera_lon = float(item.get("camera_lon"))

        camera_cfg = CameraConfig(
            camera_id=camera_id,
            source=source,
            camera_lat=camera_lat,
            camera_lon=camera_lon,
            lat_span=float(item.get("lat_span", args.lat_span)),
            lon_span=float(item.get("lon_span", args.lon_span)),
            post_interval=float(item.get("post_interval", args.post_interval)),
            min_confidence=float(item.get("min_confidence", args.min_confidence)),
            source_label=str(item.get("source_label", f"camera_yolo_{camera_id}")),
            calibration_file=item.get("calibration_file") or args.calibration_file,
            enabled=enabled,
        )
        cameras.append(camera_cfg)

    if not cameras:
        raise SystemExit(f"No enabled camera entries found in config: {args.config}")
    return cameras


def run(args: argparse.Namespace) -> None:
    cameras = load_camera_configs(args)
    stop_event = threading.Event()

    if len(cameras) == 1:
        run_camera_worker(args, cameras[0], stop_event)
        return

    print(f"Launching multi-camera YOLO pipeline with {len(cameras)} streams")
    threads: List[threading.Thread] = []
    for camera_cfg in cameras:
        thread = threading.Thread(
            target=run_camera_worker,
            args=(args, camera_cfg, stop_event),
            name=f"worker-{camera_cfg.camera_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    try:
        while not stop_event.is_set():
            for thread in threads:
                if not thread.is_alive():
                    print(f"WARN worker stopped unexpectedly: {thread.name}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopping multi-camera workers...")
        stop_event.set()

    for thread in threads:
        thread.join(timeout=3.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YOLO sensor -> Project Fosu ingest API")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Ingest endpoint URL")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLO model weights path")
    parser.add_argument(
        "--classes",
        default=(
            "person,bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe,"
            "car,motorcycle,bicycle,bus,truck"
        ),
        help=(
            "Comma-separated YOLO class names; default covers common people, "
            "animals, and vehicles"
        ),
    )
    parser.add_argument(
        "--low-light",
        action="store_true",
        help="Brighten dark frames and improve local contrast before detection",
    )
    parser.add_argument(
        "--infrared",
        action="store_true",
        help="Preprocess monochrome IR camera frames for YOLO detection",
    )
    parser.add_argument("--config", help="Path to multi-camera JSON config")

    parser.add_argument("--camera-id", default="cam-1", help="Single-camera mode identifier")
    parser.add_argument("--source", type=parse_source, default=0, help="Camera index, file path, or RTSP URL")
    parser.add_argument("--camera-lat", type=float, default=6.1219, help="Fixed camera latitude")
    parser.add_argument("--camera-lon", type=float, default=1.1974, help="Fixed camera longitude")
    parser.add_argument(
        "--calibration-file",
        default=None,
        help="Optional zone calibration JSON file",
    )
    parser.add_argument(
        "--lat-span",
        type=float,
        default=0.0015,
        help="Fallback latitude spread around camera point",
    )
    parser.add_argument(
        "--lon-span",
        type=float,
        default=0.0015,
        help="Fallback longitude spread around camera point",
    )
    parser.add_argument(
        "--post-interval",
        type=float,
        default=5.0,
        help="Minimum seconds between event posts",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.45,
        help="YOLO confidence threshold for selected detections",
    )
    parser.add_argument(
        "--inference-confidence",
        type=float,
        default=0.20,
        help="Minimum confidence used by YOLO before post-processing",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="YOLO inference image size; use 960 or 1280 for distant people",
    )
    parser.add_argument(
        "--source-label",
        default="camera_yolo",
        help="Value for the API payload 'source' field",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=5.0,
        help="HTTP timeout (seconds) when posting /ingest events",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=5.0,
        help="Delay before reconnecting a failed camera source",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Show annotated preview windows (press q to stop all workers)",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    run(parser.parse_args())

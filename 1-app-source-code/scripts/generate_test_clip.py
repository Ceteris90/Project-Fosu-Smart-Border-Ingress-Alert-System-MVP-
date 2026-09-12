"""Generate the synthetic "night / IR" test clip used by the sensor-testing
section of the README (.local/videos/vtest-night-ir.avi).

.local/ is git-ignored, so this clip never travels with the repo -- run this
once per machine to (re)create it. It starts from a real photo with real
pedestrians (Ultralytics' own bus.jpg demo image, bundled with the
`ultralytics` pip package) and renders a short clip that simulates severe
illumination loss, IR-style monochrome output, sensor noise, and lens
falloff, while keeping the pedestrians detectable -- for repeatable local
pipeline testing of scripts/yolo_sensor.py.

Run with the project virtualenv active:
    python3 1-app-source-code/scripts/generate_test_clip.py
"""
import argparse
from pathlib import Path

import cv2
import numpy as np


def find_source_image() -> Path:
    import ultralytics

    assets_dir = Path(ultralytics.__file__).resolve().parent / "assets"
    candidate = assets_dir / "bus.jpg"
    if not candidate.exists():
        raise SystemExit(
            f"Expected Ultralytics sample image not found: {candidate}. "
            "Reinstall requirements.txt or pass --source-image explicitly."
        )
    return candidate


def build_vignette(width: int, height: int, strength: float) -> np.ndarray:
    """Radial darkening mask simulating lens falloff (1.0 center -> 1-strength at the corners)."""
    y, x = np.ogrid[:height, :width]
    cx, cy = width / 2, height / 2
    max_dist = np.hypot(cx, cy)
    dist = np.hypot(x - cx, y - cy) / max_dist
    mask = 1.0 - strength * (dist**2)
    return np.clip(mask, 1.0 - strength, 1.0).astype(np.float32)


def degrade_frame(
    frame: np.ndarray, vignette: np.ndarray, brightness: float, noise_sigma: float
) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray *= brightness
    gray *= vignette
    noise = np.random.normal(0, noise_sigma, gray.shape).astype(np.float32)
    gray = np.clip(gray + noise, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".local/videos/vtest-night-ir.avi")
    parser.add_argument("--source-image", default=None, help="Override the source photo")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument(
        "--brightness", type=float, default=0.28,
        help="Multiplier simulating severe illumination loss",
    )
    parser.add_argument(
        "--noise-sigma", type=float, default=14.0, help="Gaussian sensor-noise standard deviation"
    )
    parser.add_argument(
        "--vignette-strength", type=float, default=0.55,
        help="0-1 lens falloff darkening at the corners",
    )
    parser.add_argument(
        "--jitter-px", type=int, default=6, help="Max random pan per frame, simulating a handheld camera"
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed, for a repeatable clip")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    source_path = Path(args.source_image) if args.source_image else find_source_image()
    source = cv2.imread(str(source_path))
    if source is None:
        raise SystemExit(f"Could not read source image: {source_path}")
    height, width = source.shape[:2]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vignette = build_vignette(width, height, args.vignette_strength)

    writer = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"MJPG"), args.fps, (width, height)
    )
    if not writer.isOpened():
        raise SystemExit("Failed to open VideoWriter -- is an AVI/MJPG codec available?")

    rng = np.random.default_rng(seed=args.seed)
    np.random.seed(args.seed)
    total_frames = int(args.seconds * args.fps)
    pan_x, pan_y = 0, 0
    for _ in range(total_frames):
        pan_x = int(np.clip(pan_x + rng.integers(-args.jitter_px, args.jitter_px + 1), -20, 20))
        pan_y = int(np.clip(pan_y + rng.integers(-args.jitter_px, args.jitter_px + 1), -20, 20))
        translation = np.float32([[1, 0, pan_x], [0, 1, pan_y]])
        panned = cv2.warpAffine(source, translation, (width, height), borderMode=cv2.BORDER_REFLECT)
        frame = degrade_frame(panned, vignette, args.brightness, args.noise_sigma)
        writer.write(frame)
    writer.release()

    print(f"Wrote {total_frames} frames ({args.seconds:.1f}s @ {args.fps}fps) to {output_path}")
    print(f"Source photo: {source_path}")


if __name__ == "__main__":
    main()

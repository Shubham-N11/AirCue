"""One-off vision latency spike. Not collected by pytest and not a CI gate.

Run on the hardware being evaluated; the output is host-specific.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from aircue.capture import Frame
from aircue.vision.features import extract_hand_record
from aircue.vision.tracker import MediaPipeHandTracker

TARGET_WIDTH = 640
TARGET_HEIGHT = 360


def letterbox(image: np.ndarray) -> np.ndarray:
    scale = min(TARGET_WIDTH / image.shape[1], TARGET_HEIGHT / image.shape[0])
    width = max(1, int(round(image.shape[1] * scale)))
    height = max(1, int(round(image.shape[0] * scale)))
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    top = (TARGET_HEIGHT - height) // 2
    left = (TARGET_WIDTH - width) // 2
    return cv2.copyMakeBorder(
        resized,
        top,
        TARGET_HEIGHT - height - top,
        left,
        TARGET_WIDTH - width - left,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def measure(
    tracker: MediaPipeHandTracker,
    image: np.ndarray,
    *,
    samples: int,
    warmup: int,
    confidence: float,
    finger_angle: float,
) -> dict[str, object]:
    detect_ms: list[float] = []
    feature_ms: list[float] = []
    hands = 0
    for index in range(warmup + samples):
        frame = Frame(image, time.monotonic_ns(), index)
        started = time.perf_counter_ns()
        observations = tracker.detect(frame)
        detect_elapsed = (time.perf_counter_ns() - started) / 1_000_000

        started = time.perf_counter_ns()
        for observation in observations:
            extract_hand_record(
                observation,
                confidence_threshold=confidence,
                finger_extended_angle_deg=finger_angle,
            )
        feature_elapsed = (time.perf_counter_ns() - started) / 1_000_000

        if index >= warmup:
            detect_ms.append(detect_elapsed)
            feature_ms.append(feature_elapsed)
            hands = max(hands, len(observations))

    recognition_ms = [a + b for a, b in zip(detect_ms, feature_ms, strict=True)]
    return {
        "samples": samples,
        "warmup": warmup,
        "detect_p50_ms": percentile(detect_ms, 0.50),
        "detect_p95_ms": percentile(detect_ms, 0.95),
        "feature_p50_ms": percentile(feature_ms, 0.50),
        "feature_p95_ms": percentile(feature_ms, 0.95),
        "recognition_compute_p50_ms": percentile(recognition_ms, 0.50),
        "recognition_compute_p95_ms": percentile(recognition_ms, 0.95),
        "hands_detected_max": hands,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="MediaPipe hand_landmarker.task path")
    parser.add_argument("--image", required=True, help="image containing one or more hands")
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--finger-angle", type=float, default=160.0)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup must not be negative")

    model_path = Path(args.model)
    image_path = Path(args.image)
    image = cv2.imread(str(image_path))
    if image is None:
        parser.error(f"cannot read image: {image_path}")
    frame_image = letterbox(image)

    tracker = MediaPipeHandTracker(
        str(model_path),
        confidence_threshold=args.confidence,
        max_hands=2,
    )
    try:
        measurements = measure(
            tracker,
            frame_image,
            samples=args.samples,
            warmup=args.warmup,
            confidence=args.confidence,
            finger_angle=args.finger_angle,
        )
    finally:
        tracker.close()

    report = {
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "tracker": {
            "runtime": "mediapipe.tasks.HandLandmarker",
            "mediapipe_version": mp.__version__,
            "running_mode": "IMAGE",
            "max_hands": 2,
            "confidence_threshold": args.confidence,
        },
        "model": {
            "path": str(model_path),
            "bytes": model_path.stat().st_size,
            "sha256": sha256(model_path),
        },
        "image": {
            "path": str(image_path),
            "source_width": int(image.shape[1]),
            "source_height": int(image.shape[0]),
            "frame_width": TARGET_WIDTH,
            "frame_height": TARGET_HEIGHT,
            "fit": "aspect-preserving letterbox",
        },
        "measurement": measurements,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Hand-tracker protocol and MediaPipe Tasks adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from aircue.capture import Frame
from aircue.vision.types import (
    HandObservation,
    Landmark,
    TrackerError,
    TrackerInitializationError,
)


class HandTracker(Protocol):
    def detect(self, frame: Frame) -> tuple[HandObservation, ...]: ...

    def close(self) -> None: ...


LandmarkerFactory = Callable[[], Any]


class MediaPipeHandTracker:
    """MediaPipe Tasks hand landmarker in IMAGE mode.

    IMAGE mode is used because the runtime's VIDEO mode measured roughly six times
    slower and does not expose a stable tracking identity. Identity continuity is
    owned by the primary-hand selector.
    """

    def __init__(
        self,
        model_path: str,
        *,
        confidence_threshold: float = 0.5,
        max_hands: int = 2,
        landmarker_factory: LandmarkerFactory | None = None,
    ) -> None:
        if not model_path.strip():
            raise TrackerInitializationError("hand-landmark model path is not configured")
        resolved = Path(model_path)
        if not resolved.is_file():
            raise TrackerInitializationError(f"hand-landmark model not found: {resolved}")

        self._confidence_threshold = confidence_threshold
        factory = landmarker_factory
        if factory is None:
            factory = lambda: _create_landmarker(resolved, max_hands, confidence_threshold)  # noqa: E731
        try:
            self._landmarker = factory()
        except TrackerInitializationError:
            raise
        except Exception as exc:
            raise TrackerInitializationError(f"hand-landmark model failed to load: {exc}") from exc

    def detect(self, frame: Frame) -> tuple[HandObservation, ...]:
        rgb = np.ascontiguousarray(cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect(mp_image)
        except Exception as exc:
            raise TrackerError(f"hand tracking failed: {exc}") from exc

        observations: list[HandObservation] = []
        handedness_groups = result.handedness or []
        for index, raw_landmarks in enumerate(result.hand_landmarks or []):
            categories = handedness_groups[index] if index < len(handedness_groups) else []
            score = float(categories[0].score) if categories else 0.0
            if score < self._confidence_threshold:
                continue
            label = str(categories[0].category_name) if categories else "Unknown"
            landmarks = tuple(
                Landmark(float(item.x), float(item.y), float(item.z), score)
                for item in raw_landmarks
            )
            observations.append(
                HandObservation(
                    track_id=len(observations),
                    landmarks=landmarks,
                    confidence=score,
                    handedness=label,
                )
            )
        return tuple(observations)

    def close(self) -> None:
        close = getattr(self._landmarker, "close", None)
        if close is not None:
            close()


def _create_landmarker(
    model_path: Path, max_hands: int, confidence_threshold: float
) -> vision.HandLandmarker:
    options = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=max_hands,
        min_hand_detection_confidence=confidence_threshold,
        min_hand_presence_confidence=confidence_threshold,
    )
    return vision.HandLandmarker.create_from_options(options)

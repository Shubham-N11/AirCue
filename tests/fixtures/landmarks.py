"""Synthetic hand landmarks shared by unit and integration tests."""

from __future__ import annotations

from aircue.vision.types import HandObservation, Landmark

# A right hand facing the camera, all five fingers extended, in normalized coordinates.
BASE_POSE: dict[int, tuple[float, float, float]] = {
    0: (0.50, 0.70, 0.0),
    1: (0.42, 0.65, 0.0),
    2: (0.36, 0.62, 0.0),
    3: (0.31, 0.58, 0.0),
    4: (0.26, 0.54, 0.0),
    5: (0.45, 0.47, 0.0),
    6: (0.45, 0.40, 0.0),
    7: (0.45, 0.35, 0.0),
    8: (0.45, 0.30, 0.0),
    9: (0.50, 0.45, 0.0),
    10: (0.50, 0.37, 0.0),
    11: (0.50, 0.32, 0.0),
    12: (0.50, 0.27, 0.0),
    13: (0.55, 0.47, 0.0),
    14: (0.55, 0.40, 0.0),
    15: (0.55, 0.35, 0.0),
    16: (0.55, 0.31, 0.0),
    17: (0.60, 0.50, 0.0),
    18: (0.60, 0.44, 0.0),
    19: (0.60, 0.40, 0.0),
    20: (0.60, 0.36, 0.0),
}


def make_landmarks(
    overrides: dict[int, tuple[float, float, float, float]] | None = None,
    *,
    confidence: float = 0.9,
    count: int = 21,
) -> tuple[Landmark, ...]:
    overrides = overrides or {}
    result: list[Landmark] = []
    for index in range(count):
        x, y, z = BASE_POSE[index]
        score = confidence
        if index in overrides:
            x, y, z, score = overrides[index]
        result.append(Landmark(x, y, z, score))
    return tuple(result)


def make_observation(
    overrides: dict[int, tuple[float, float, float, float]] | None = None,
    *,
    confidence: float = 0.9,
    count: int = 21,
    track_id: int = 0,
    handedness: str = "Right",
) -> HandObservation:
    return HandObservation(
        track_id=track_id,
        landmarks=make_landmarks(overrides, confidence=confidence, count=count),
        confidence=confidence,
        handedness=handedness,
    )

"""The fixed gesture vocabulary."""

from __future__ import annotations

from enum import StrEnum


class Gesture(StrEnum):
    OPEN_PALM_CLOCKWISE = "open_palm_clockwise"
    OPEN_PALM_COUNTERCLOCKWISE = "open_palm_counterclockwise"
    FIST = "fist"
    THUMBS_UP = "thumbs_up"
    PINCH = "pinch"
    POINTER_POSE = "pointer_pose"
    PINCH_RELEASE = "pinch_release"
    PEACE = "peace"
    SHAKA = "shaka"


GESTURES = tuple(Gesture)

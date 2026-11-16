"""Landmark and hand observation types."""

from __future__ import annotations

from dataclasses import dataclass

WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

LANDMARK_COUNT = 21
FINGERTIPS = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)
PALM_POINTS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float
    confidence: float


@dataclass(frozen=True)
class HandObservation:
    """One detected hand in normalized image coordinates.

    ``track_id`` is a per-frame detection index. Stable identity across frames is
    assigned by the primary-hand selector, not by the MediaPipe IMAGE-mode adapter.
    MediaPipe exposes hand-level confidence only, so every landmark carries that score.
    """

    track_id: int
    landmarks: tuple[Landmark, ...]
    confidence: float
    handedness: str


class TrackerError(RuntimeError):
    """Base class for hand-tracker failures."""


class TrackerInitializationError(TrackerError):
    """The tracker could not be initialized."""


class InvalidLandmarkFrameError(ValueError):
    """A landmark coordinate is non-finite or outside normalized image bounds."""


@dataclass(frozen=True)
class StageTimestamps:
    preprocess_done_ns: int | None = None
    inference_done_ns: int | None = None
    features_done_ns: int | None = None


FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")


@dataclass(frozen=True)
class HandFeatures:
    wrist_angle_deg: float | None
    pinch_distance: float | None
    palm_scale: float | None
    openness: float | None
    finger_extension: tuple[bool | None, ...]


@dataclass(frozen=True)
class HandRecord:
    track_id: int
    handedness: str
    confidence: float
    landmarks: tuple[Landmark | None, ...]
    valid: tuple[bool, ...]
    features: HandFeatures


@dataclass(frozen=True)
class PresenceStatus:
    present: bool
    first_absence_ts_ns: int | None = None
    completed_absence_ns: int | None = None

    def absence_elapsed_ns(self, now_ns: int) -> int:
        if self.present or self.first_absence_ts_ns is None:
            return 0
        return max(0, now_ns - self.first_absence_ts_ns)


@dataclass(frozen=True)
class FrameRecord:
    capture_ts_ns: int
    frame_sequence: int
    stage_timestamps: StageTimestamps
    hand: HandRecord | None
    hands_detected: int
    presence: PresenceStatus
    invalid_landmark_frame: bool = False

"""Per-landmark validity and normalized geometric features."""

from __future__ import annotations

import math

from aircue.vision.types import (
    FINGER_NAMES,
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    LANDMARK_COUNT,
    MIDDLE_MCP,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_MCP,
    PINKY_PIP,
    PINKY_TIP,
    RING_MCP,
    RING_PIP,
    RING_TIP,
    THUMB_IP,
    THUMB_MCP,
    THUMB_TIP,
    WRIST,
    FrameRecord,
    HandFeatures,
    HandObservation,
    HandRecord,
    InvalidLandmarkFrameError,
    Landmark,
    PresenceStatus,
    StageTimestamps,
)

_FINGER_JOINTS = (
    (THUMB_MCP, THUMB_IP, THUMB_TIP),
    (INDEX_MCP, INDEX_PIP, INDEX_TIP),
    (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP),
    (RING_MCP, RING_PIP, RING_TIP),
    (PINKY_MCP, PINKY_PIP, PINKY_TIP),
)


def validate_observation(
    observation: HandObservation, confidence_threshold: float
) -> tuple[tuple[Landmark | None, ...], tuple[bool, ...]]:
    """Return exactly 21 landmarks and validity flags.

    Raises InvalidLandmarkFrameError when a present landmark has a non-finite or
    out-of-range coordinate. Missing and low-confidence landmarks are marked invalid
    without rejecting the frame.
    """
    if len(observation.landmarks) > LANDMARK_COUNT:
        raise InvalidLandmarkFrameError(
            f"hand has {len(observation.landmarks)} landmarks, expected at most {LANDMARK_COUNT}"
        )

    padded: list[Landmark | None] = list(observation.landmarks)
    padded.extend([None] * (LANDMARK_COUNT - len(padded)))
    valid: list[bool] = []
    for index, landmark in enumerate(padded):
        if landmark is None:
            valid.append(False)
            continue
        if not all(math.isfinite(value) for value in (landmark.x, landmark.y, landmark.z)):
            raise InvalidLandmarkFrameError(f"landmark {index} is not finite")
        if not (0.0 <= landmark.x <= 1.0 and 0.0 <= landmark.y <= 1.0):
            raise InvalidLandmarkFrameError(f"landmark {index} is outside normalized bounds")
        valid.append(landmark.confidence >= confidence_threshold)
    return tuple(padded), tuple(valid)


def extract_hand_record(
    observation: HandObservation,
    *,
    confidence_threshold: float,
    finger_extended_angle_deg: float,
) -> HandRecord:
    landmarks, valid = validate_observation(observation, confidence_threshold)
    usable = {
        index: landmark
        for index, (landmark, is_valid) in enumerate(zip(landmarks, valid, strict=True))
        if is_valid and landmark is not None
    }
    palm_scale = _palm_scale(usable)
    finger_extension = tuple(
        _finger_extended(usable, joints, finger_extended_angle_deg) for joints in _FINGER_JOINTS
    )
    openness = (
        sum(1 for extended in finger_extension if extended) / len(FINGER_NAMES)
        if all(extended is not None for extended in finger_extension)
        else None
    )
    features = HandFeatures(
        wrist_angle_deg=_wrist_angle(usable),
        pinch_distance=_pinch_distance(usable, palm_scale),
        palm_scale=palm_scale,
        openness=openness,
        finger_extension=finger_extension,
    )
    return HandRecord(
        track_id=observation.track_id,
        handedness=observation.handedness,
        confidence=observation.confidence,
        landmarks=landmarks,
        valid=valid,
        features=features,
    )


def build_frame_record(
    *,
    capture_ts_ns: int,
    frame_sequence: int,
    observation: HandObservation | None,
    hands_detected: int,
    confidence_threshold: float,
    finger_extended_angle_deg: float,
    stage_timestamps: StageTimestamps | None = None,
    presence: PresenceStatus | None = None,
) -> FrameRecord:
    hand = (
        extract_hand_record(
            observation,
            confidence_threshold=confidence_threshold,
            finger_extended_angle_deg=finger_extended_angle_deg,
        )
        if observation is not None
        else None
    )
    return FrameRecord(
        capture_ts_ns=capture_ts_ns,
        frame_sequence=frame_sequence,
        stage_timestamps=stage_timestamps or StageTimestamps(),
        hand=hand,
        hands_detected=hands_detected,
        presence=presence or PresenceStatus(present=observation is not None),
    )


def _palm_scale(landmarks: dict[int, Landmark]) -> float | None:
    wrist = landmarks.get(WRIST)
    middle = landmarks.get(MIDDLE_MCP)
    if wrist is None or middle is None:
        return None
    scale = math.hypot(middle.x - wrist.x, middle.y - wrist.y)
    return scale if scale > 0 else None


def _wrist_angle(landmarks: dict[int, Landmark]) -> float | None:
    wrist = landmarks.get(WRIST)
    middle = landmarks.get(MIDDLE_MCP)
    if wrist is None or middle is None:
        return None
    return math.degrees(math.atan2(middle.x - wrist.x, wrist.y - middle.y))


def _pinch_distance(landmarks: dict[int, Landmark], palm_scale: float | None) -> float | None:
    thumb = landmarks.get(THUMB_TIP)
    index = landmarks.get(INDEX_TIP)
    if thumb is None or index is None or palm_scale is None:
        return None
    return math.hypot(thumb.x - index.x, thumb.y - index.y) / palm_scale


def _finger_extended(
    landmarks: dict[int, Landmark],
    joints: tuple[int, int, int],
    threshold_deg: float,
) -> bool | None:
    base = landmarks.get(joints[0])
    middle = landmarks.get(joints[1])
    tip = landmarks.get(joints[2])
    if base is None or middle is None or tip is None:
        return None
    folding = _angle_deg(middle, base, tip)
    return folding >= threshold_deg


def _angle_deg(vertex: Landmark, first: Landmark, second: Landmark) -> float:
    ax, ay = first.x - vertex.x, first.y - vertex.y
    bx, by = second.x - vertex.x, second.y - vertex.y
    norm = math.hypot(ax, ay) * math.hypot(bx, by)
    if norm == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / norm))
    return math.degrees(math.acos(cosine))

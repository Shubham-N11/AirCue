"""Per-landmark validity and normalized geometric features."""

from __future__ import annotations

import math

from aircue.vision.geometry import (
    finger_extension,
    hand_openness,
    joint_angle_3d_deg,
    palm_scale,
    pinch_distance,
    wrist_angle,
)
from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    LANDMARK_COUNT,
    FrameRecord,
    HandFeatures,
    HandObservation,
    HandRecord,
    InvalidLandmarkFrameError,
    Landmark,
    PresenceStatus,
    StageTimestamps,
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


def _index_angle_3d(
    world_landmarks: tuple[Landmark, ...], valid: tuple[bool, ...]
) -> float | None:
    indices = (INDEX_MCP, INDEX_PIP, INDEX_TIP)
    if len(world_landmarks) <= INDEX_TIP or not all(valid[index] for index in indices):
        return None
    mcp, pip, tip = (world_landmarks[index] for index in indices)
    if not all(
        math.isfinite(value)
        for point in (mcp, pip, tip)
        for value in (point.x, point.y, point.z)
    ):
        return None
    return joint_angle_3d_deg(pip, mcp, tip)


def extract_hand_record(
    observation: HandObservation,
    *,
    confidence_threshold: float,
    finger_extended_angle_deg: float,
) -> HandRecord:
    landmarks, valid = validate_observation(observation, confidence_threshold)
    scale = palm_scale(landmarks, valid)
    extensions = finger_extension(landmarks, valid, finger_extended_angle_deg)
    features = HandFeatures(
        wrist_angle_deg=wrist_angle(landmarks, valid),
        pinch_distance=pinch_distance(landmarks, valid),
        palm_scale=scale,
        openness=hand_openness(extensions),
        finger_extension=extensions,
        index_angle_3d_deg=_index_angle_3d(observation.world_landmarks, valid),
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

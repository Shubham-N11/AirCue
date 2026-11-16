import math

import pytest

from aircue.vision.features import build_frame_record, extract_hand_record, validate_observation
from aircue.vision.types import (
    INDEX_TIP,
    MIDDLE_MCP,
    THUMB_TIP,
    WRIST,
    InvalidLandmarkFrameError,
    StageTimestamps,
)
from tests.fixtures.landmarks import make_observation


def extract(observation, confidence=0.5):
    return extract_hand_record(
        observation,
        confidence_threshold=confidence,
        finger_extended_angle_deg=160.0,
    )


def test_valid_hand_has_all_features() -> None:
    record = extract(make_observation())
    assert len(record.landmarks) == 21
    assert all(record.valid)
    assert record.features.wrist_angle_deg == pytest.approx(0.0, abs=1e-6)
    assert record.features.palm_scale == pytest.approx(0.25)
    assert record.features.pinch_distance is not None
    assert record.features.openness == pytest.approx(1.0)
    assert record.features.finger_extension == (True, True, True, True, True)


def test_nan_landmark_rejects_frame() -> None:
    observation = make_observation({5: (math.nan, 0.5, 0.0, 0.9)})
    with pytest.raises(InvalidLandmarkFrameError, match="not finite"):
        validate_observation(observation, 0.5)


def test_infinite_landmark_rejects_frame() -> None:
    observation = make_observation({5: (0.5, math.inf, 0.0, 0.9)})
    with pytest.raises(InvalidLandmarkFrameError, match="not finite"):
        validate_observation(observation, 0.5)


def test_out_of_range_landmark_rejects_frame() -> None:
    observation = make_observation({5: (1.2, 0.5, 0.0, 0.9)})
    with pytest.raises(InvalidLandmarkFrameError, match="outside normalized bounds"):
        validate_observation(observation, 0.5)


def test_missing_landmarks_are_marked_invalid() -> None:
    observation = make_observation(count=10)
    record = extract(observation)
    assert sum(record.valid) == 10
    assert all(record.valid[:10])
    assert not any(record.valid[10:])
    assert record.features.palm_scale is not None
    assert record.features.wrist_angle_deg is not None
    assert record.features.pinch_distance is not None
    assert record.features.openness is None
    assert record.features.finger_extension == (True, True, None, None, None)


def test_low_confidence_landmarks_are_excluded() -> None:
    observation = make_observation(
        {
            THUMB_TIP: (0.26, 0.54, 0.0, 0.2),
            INDEX_TIP: (0.45, 0.30, 0.0, 0.2),
        }
    )
    record = extract(observation)
    assert record.valid[THUMB_TIP] is False
    assert record.valid[INDEX_TIP] is False
    assert record.features.pinch_distance is None
    assert record.features.openness is None
    assert record.features.palm_scale is not None


def test_feature_depending_on_invalid_landmark_is_unavailable() -> None:
    observation = make_observation({MIDDLE_MCP: (0.50, 0.45, 0.0, 0.1)})
    record = extract(observation)
    assert record.valid[MIDDLE_MCP] is False
    assert record.features.wrist_angle_deg is None
    assert record.features.palm_scale is None
    assert record.features.pinch_distance is None


def test_landmarks_beyond_twenty_one_are_rejected() -> None:
    observation = make_observation()
    extra = observation.landmarks + (observation.landmarks[0],)
    too_many = type(observation)(
        track_id=0,
        landmarks=extra,
        confidence=observation.confidence,
        handedness=observation.handedness,
    )
    with pytest.raises(InvalidLandmarkFrameError, match="at most 21"):
        validate_observation(too_many, 0.5)


def test_features_are_resolution_independent() -> None:
    pixels = {
        640: [(x * 640, y * 360, z) for x, y, z in _pose_values()],
        1280: [(x * 1280, y * 720, z) for x, y, z in _pose_values()],
    }
    records = []
    for width, height in ((640, 360), (1280, 720)):
        points = pixels[width]
        overrides = {
            index: (x / width, y / height, z, 0.9) for index, (x, y, z) in enumerate(points)
        }
        records.append(extract(make_observation(overrides)))

    left, right = records
    assert left.features.palm_scale == pytest.approx(right.features.palm_scale)
    assert left.features.pinch_distance == pytest.approx(right.features.pinch_distance)
    assert left.features.wrist_angle_deg == pytest.approx(right.features.wrist_angle_deg)
    assert left.features.openness == right.features.openness
    assert left.features.finger_extension == right.features.finger_extension


def test_frame_record_carries_timestamps_and_sequence() -> None:
    stages = StageTimestamps(preprocess_done_ns=10, inference_done_ns=20, features_done_ns=30)
    record = build_frame_record(
        capture_ts_ns=5,
        frame_sequence=7,
        observation=make_observation(),
        hands_detected=1,
        confidence_threshold=0.5,
        finger_extended_angle_deg=160.0,
        stage_timestamps=stages,
    )
    assert record.capture_ts_ns == 5
    assert record.frame_sequence == 7
    assert record.stage_timestamps == stages
    assert record.hands_detected == 1
    assert record.hand is not None
    assert record.hand.landmarks[WRIST] is not None


def _pose_values() -> list[tuple[float, float, float]]:
    from tests.fixtures.landmarks import BASE_POSE

    return [BASE_POSE[index] for index in range(21)]

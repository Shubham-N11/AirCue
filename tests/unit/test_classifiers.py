import math

import pytest

from aircue.gestures.classifiers import (
    is_fist,
    is_open_palm,
    is_peace,
    is_pinch,
    is_pointer_pose,
    is_shaka,
    is_thumbs_up,
)
from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    THUMB_MCP,
    THUMB_TIP,
    HandFeatures,
    HandRecord,
)
from tests.fixtures.landmarks import BASE_POSE, make_landmarks


def index_landmarks(angle_deg: float) -> dict[int, tuple[float, float, float, float]]:
    mcp = (0.45, 0.60)
    pip = (0.45, 0.45)
    radians = math.radians(90.0 - angle_deg)
    tip = (pip[0] + 0.15 * math.cos(radians), pip[1] + 0.15 * math.sin(radians))
    return {
        INDEX_MCP: (*mcp, 0.0, 0.9),
        INDEX_PIP: (*pip, 0.0, 0.9),
        INDEX_TIP: (*tip, 0.0, 0.9),
    }


def hand(
    extensions: tuple[bool | None, ...],
    *,
    pinch_distance: float | None = 1.0,
    thumb_tip: tuple[float, float] | None = None,
    index_angle_deg: float | None = None,
) -> HandRecord:
    overrides = {}
    if thumb_tip is not None:
        overrides[THUMB_TIP] = (thumb_tip[0], thumb_tip[1], 0.0, 0.9)
    if index_angle_deg is not None:
        overrides.update(index_landmarks(index_angle_deg))
    features = HandFeatures(
        wrist_angle_deg=0.0,
        pinch_distance=pinch_distance,
        palm_scale=0.25,
        openness=None,
        finger_extension=extensions,
    )
    return HandRecord(
        track_id=0,
        handedness="Right",
        confidence=0.9,
        landmarks=make_landmarks(overrides),
        valid=(True,) * 21,
        features=features,
    )


def thumb_tip_at(degrees_from_up: float) -> tuple[float, float]:
    mcp_x, mcp_y, _ = BASE_POSE[THUMB_MCP]
    radians = math.radians(degrees_from_up)
    return (mcp_x + 0.3 * math.sin(radians), mcp_y - 0.3 * math.cos(radians))


@pytest.mark.parametrize(
    ("classifier", "extensions"),
    [
        (is_fist, (False, False, False, False, False)),
        (is_open_palm, (True, True, True, True, True)),
        (is_peace, (False, True, True, False, False)),
        (is_shaka, (True, False, False, False, True)),
        (is_pointer_pose, (True, True, False, False, False)),
    ],
)
def test_static_pose_matches_its_pattern(classifier, extensions) -> None:
    assert classifier(hand(extensions)) is True


def test_pinch_matches_distance_below_threshold() -> None:
    assert is_pinch(hand((True, True, True, True, True), pinch_distance=0.219)) is True


def test_pinch_does_not_match_at_the_threshold() -> None:
    assert is_pinch(hand((True, True, True, True, True), pinch_distance=0.22)) is False
    assert is_pinch(hand((True, True, True, True, True), pinch_distance=0.221)) is False


def test_pointer_pose_requires_separation_above_threshold() -> None:
    pose = (True, True, False, False, False)
    assert is_pointer_pose(hand(pose, pinch_distance=0.401)) is True
    assert is_pointer_pose(hand(pose, pinch_distance=0.40)) is False
    assert is_pointer_pose(hand(pose, pinch_distance=0.399)) is False


def test_pointer_pose_tolerates_a_slightly_bent_index() -> None:
    # Real pointer frames measure 140-158 degrees at the PIP joint while pointing.
    pose = (True, False, False, False, False)
    assert is_pointer_pose(hand(pose, index_angle_deg=145.0)) is True
    assert is_pointer_pose(hand(pose, index_angle_deg=144.9)) is False


def test_pointer_pose_rejects_a_curled_index() -> None:
    pose = (True, False, False, False, False)
    assert is_pointer_pose(hand(pose, index_angle_deg=120.0)) is False


def test_pointer_pose_uses_the_configured_extension_threshold() -> None:
    pose = (True, False, False, False, False)
    bent = hand(pose, index_angle_deg=140.0)
    assert is_pointer_pose(bent) is False
    assert is_pointer_pose(bent, extended_angle_deg=150.0) is True


def test_thumbs_up_requires_an_upward_thumb() -> None:
    pose = (True, False, False, False, False)
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(0))) is True
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(45))) is True
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(46))) is False
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(90))) is False
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(180))) is False


def test_thumbs_up_requires_the_other_fingers_to_be_curled() -> None:
    pose = (True, True, False, False, False)
    assert is_thumbs_up(hand(pose, thumb_tip=thumb_tip_at(0))) is False


@pytest.mark.parametrize(
    ("classifier", "extensions"),
    [
        (is_fist, (True, False, False, False, False)),
        (is_open_palm, (True, True, True, True, False)),
        (is_peace, (False, True, True, True, False)),
        (is_shaka, (False, False, False, False, True)),
        (is_pointer_pose, (True, True, True, False, False)),
    ],
)
def test_static_pose_rejects_a_different_pattern(classifier, extensions) -> None:
    assert classifier(hand(extensions)) is False


def test_similar_poses_do_not_match_each_other() -> None:
    shaka = hand((True, False, False, False, True))
    thumbs_up = hand((True, False, False, False, False), thumb_tip=thumb_tip_at(0))
    peace = hand((False, True, True, False, False))
    pointer = hand((True, True, False, False, False), pinch_distance=1.0)

    assert is_shaka(thumbs_up) is False
    assert is_thumbs_up(shaka) is False
    assert is_peace(pointer) is False
    assert is_pointer_pose(peace) is False


@pytest.mark.parametrize(
    "classifier",
    [is_fist, is_open_palm, is_peace, is_shaka, is_thumbs_up, is_pointer_pose],
)
def test_pattern_classifiers_reject_unknown_finger_state(classifier) -> None:
    occluded = hand((True, None, True, True, True), thumb_tip=thumb_tip_at(0))
    assert classifier(occluded) is False


def test_pinch_classifiers_reject_unavailable_distance() -> None:
    pose = (True, True, False, False, False)
    assert is_pinch(hand(pose, pinch_distance=None)) is False
    assert is_pointer_pose(hand(pose, pinch_distance=None)) is False


def test_thumbs_up_rejects_missing_thumb_landmark() -> None:
    occluded = hand((True, False, False, False, False))
    landmarks = list(occluded.landmarks)
    landmarks[THUMB_TIP] = None
    valid = list(occluded.valid)
    valid[THUMB_TIP] = False
    assert (
        is_thumbs_up(
            HandRecord(
                track_id=occluded.track_id,
                handedness=occluded.handedness,
                confidence=occluded.confidence,
                landmarks=tuple(landmarks),
                valid=tuple(valid),
                features=occluded.features,
            )
        )
        is False
    )

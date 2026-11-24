import math

import pytest

from aircue.gestures.geometry import (
    angle_from_neutral,
    to_user_perspective_angle,
    to_user_perspective_x,
    unwrap_angle_deg,
)
from aircue.vision.geometry import (
    finger_extension,
    hand_openness,
    joint_angle_3d_deg,
    joint_angle_deg,
    palm_scale,
    pinch_distance,
    usable_landmarks,
    wrist_angle,
)
from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    MIDDLE_MCP,
    THUMB_CMC,
    THUMB_IP,
    THUMB_MCP,
    THUMB_TIP,
    WRIST,
    Landmark,
)
from tests.fixtures.landmarks import make_landmarks


def pose(overrides=None, *, count: int = 21):
    return make_landmarks(overrides, count=count)


def flags(count: int = 21) -> tuple[bool, ...]:
    return (True,) * count


def landmark(x: float, y: float) -> Landmark:
    return Landmark(x, y, 0.0, 0.9)


def test_palm_scale_uses_wrist_to_middle_mcp() -> None:
    assert palm_scale(pose(), flags()) == pytest.approx(0.25)


def test_palm_scale_is_unavailable_without_required_landmark() -> None:
    invalid = list(flags())
    invalid[WRIST] = False
    assert palm_scale(pose(), invalid) is None

    points = list(pose())
    points[MIDDLE_MCP] = None
    assert palm_scale(points, flags()) is None


def test_palm_scale_is_unavailable_for_zero_distance() -> None:
    points = pose({MIDDLE_MCP: (0.50, 0.70, 0.0, 0.9)})
    assert palm_scale(points, flags()) is None


def test_usable_landmarks_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        usable_landmarks(pose(), (True,))


def test_pinch_distance_is_normalized_by_palm_scale() -> None:
    points = pose()
    thumb = points[THUMB_TIP]
    index = points[INDEX_TIP]
    expected = math.hypot(thumb.x - index.x, thumb.y - index.y) / 0.25
    assert pinch_distance(points, flags()) == pytest.approx(expected)
    assert pinch_distance(points, flags()) > 1.0


def test_pinch_distance_is_zero_at_contact() -> None:
    points = pose()
    index = points[INDEX_TIP]
    touching = pose({THUMB_TIP: (index.x, index.y, index.z, index.confidence)})
    assert pinch_distance(touching, flags()) == pytest.approx(0.0)


def test_pinch_distance_is_unavailable_without_either_tip() -> None:
    invalid = list(flags())
    invalid[THUMB_TIP] = False
    assert pinch_distance(pose(), invalid) is None

    invalid = list(flags())
    invalid[INDEX_TIP] = False
    assert pinch_distance(pose(), invalid) is None


def test_wrist_angle_is_zero_when_upright() -> None:
    assert wrist_angle(pose(), flags()) == pytest.approx(0.0, abs=1e-9)


def test_wrist_angle_sign_follows_image_space() -> None:
    right = pose({MIDDLE_MCP: (0.75, 0.70, 0.0, 0.9)})
    left = pose({MIDDLE_MCP: (0.25, 0.70, 0.0, 0.9)})
    down = pose({MIDDLE_MCP: (0.50, 0.95, 0.0, 0.9)})
    assert wrist_angle(right, flags()) == pytest.approx(90.0)
    assert wrist_angle(left, flags()) == pytest.approx(-90.0)
    assert wrist_angle(down, flags()) == pytest.approx(180.0)


def test_wrist_angle_is_unavailable_without_middle_mcp() -> None:
    invalid = list(flags())
    invalid[MIDDLE_MCP] = False
    assert wrist_angle(pose(), invalid) is None


def test_finger_extension_for_extended_fixture() -> None:
    assert finger_extension(pose(), flags()) == (True, True, True, True, True)


def test_curled_finger_is_not_extended() -> None:
    curled = pose({INDEX_TIP: (0.45, 0.46, 0.0, 0.9)})
    assert finger_extension(curled, flags())[1] is False


def test_finger_extension_is_unavailable_when_a_joint_is_missing() -> None:
    extensions = finger_extension(pose(count=7), flags(7))
    assert extensions[0] is True
    assert extensions[1:] == (None, None, None, None)


def test_finger_extension_uses_the_configured_threshold() -> None:
    def index_pose(tip_angle_deg: float):
        radians = math.radians(tip_angle_deg)
        tip = (0.5 + 0.5 * math.cos(radians), 0.5 + 0.5 * math.sin(radians))
        return pose(
            {
                INDEX_MCP: (0.5, 0.0, 0.0, 0.9),
                INDEX_PIP: (0.5, 0.5, 0.0, 0.9),
                INDEX_TIP: (tip[0], tip[1], 0.0, 0.9),
            }
        )

    assert finger_extension(index_pose(69.9), flags(), 160.0)[1] is False
    assert finger_extension(index_pose(70.1), flags(), 160.0)[1] is True


def _point_at(
    origin: tuple[float, float], degrees: float, length: float = 0.2
) -> tuple[float, float]:
    radians = math.radians(degrees)
    return (
        origin[0] + length * math.cos(radians),
        origin[1] + length * math.sin(radians),
    )


def _thumb_pose(ip_angle_deg: float, mcp_angle_deg: float):
    cmc = (0.50, 0.70)
    mcp = (0.50, 0.50)
    ip = _point_at(mcp, 90.0 - mcp_angle_deg)
    tip = _point_at(ip, 270.0 - mcp_angle_deg - ip_angle_deg)
    return pose(
        {
            THUMB_CMC: (*cmc, 0.0, 0.9),
            THUMB_MCP: (*mcp, 0.0, 0.9),
            THUMB_IP: (*ip, 0.0, 0.9),
            THUMB_TIP: (*tip, 0.0, 0.9),
        }
    )


def test_thumb_extension_tolerates_a_slightly_bent_ip_joint() -> None:
    # Pointer frames measure IP at ~145 deg while the MCP stays straight at ~178.
    hand = _thumb_pose(ip_angle_deg=145.0, mcp_angle_deg=178.0)
    assert finger_extension(hand, flags())[0] is True


def test_thumb_extension_tolerates_a_slightly_bent_mcp_joint() -> None:
    # Thumbs-up frames measure the MCP near the threshold while the IP is straight.
    hand = _thumb_pose(ip_angle_deg=178.0, mcp_angle_deg=162.0)
    assert finger_extension(hand, flags())[0] is True


def test_thumb_is_not_extended_when_both_joints_bend() -> None:
    # Fist frames measure IP at ~145 deg and MCP at ~100 deg.
    hand = _thumb_pose(ip_angle_deg=145.0, mcp_angle_deg=100.0)
    assert finger_extension(hand, flags())[0] is False


def test_hand_openness_counts_extended_fingers() -> None:
    assert hand_openness((True, True, True, True, True)) == pytest.approx(1.0)
    assert hand_openness((False, False, False, False, False)) == pytest.approx(0.0)
    assert hand_openness((True, False, True, False, False)) == pytest.approx(0.4)
    assert hand_openness((True, None, True, False, False)) is None
    assert hand_openness(()) is None


def test_joint_angle_boundaries() -> None:
    origin = landmark(0.0, 0.0)
    right = landmark(1.0, 0.0)
    up = landmark(0.0, 1.0)
    assert joint_angle_deg(origin, right, up) == pytest.approx(90.0)
    assert joint_angle_deg(origin, right, right) == pytest.approx(0.0)
    assert joint_angle_deg(origin, right, landmark(-1.0, 0.0)) == pytest.approx(180.0)
    assert joint_angle_deg(origin, origin, right) == 0.0


def test_joint_angle_3d_uses_depth() -> None:
    origin = Landmark(0.0, 0.0, 0.0, 0.9)
    right = Landmark(1.0, 0.0, 0.0, 0.9)
    forward = Landmark(0.0, 0.0, 1.0, 0.9)
    assert joint_angle_3d_deg(origin, right, forward) == pytest.approx(90.0)
    assert joint_angle_3d_deg(origin, right, origin) == 0.0


def test_user_perspective_x_is_mirrored() -> None:
    assert to_user_perspective_x(0.0) == 1.0
    assert to_user_perspective_x(1.0) == 0.0
    assert to_user_perspective_x(0.25) == pytest.approx(0.75)


def test_user_clockwise_rotation_is_positive() -> None:
    # A hand tilting toward the user's right appears tilted left in the raw image.
    assert to_user_perspective_angle(-30.0) == pytest.approx(30.0)


@pytest.mark.parametrize(
    ("image_angle", "user_angle"),
    [(0.0, 0.0), (30.0, -30.0), (-30.0, 30.0), (180.0, -180.0), (-180.0, 180.0)],
)
def test_user_perspective_angle_flips_sign(image_angle: float, user_angle: float) -> None:
    assert to_user_perspective_angle(image_angle) == pytest.approx(user_angle)


def test_user_perspective_angle_rejects_non_finite_input() -> None:
    with pytest.raises(ValueError, match="finite"):
        to_user_perspective_angle(math.nan)


@pytest.mark.parametrize(
    ("current", "neutral", "expected"),
    [
        (25.0, 0.0, 25.0),
        (-25.0, 0.0, -25.0),
        (350.0, 10.0, -20.0),
        (10.0, 350.0, 20.0),
        (180.0, 0.0, -180.0),
        (0.0, 180.0, -180.0),
    ],
)
def test_angle_from_neutral_takes_the_short_path(
    current: float, neutral: float, expected: float
) -> None:
    assert angle_from_neutral(current, neutral) == pytest.approx(expected)


def test_angle_from_neutral_rejects_non_finite_input() -> None:
    with pytest.raises(ValueError, match="finite"):
        angle_from_neutral(math.inf, 0.0)


@pytest.mark.parametrize(
    ("previous", "raw", "expected"),
    [
        (170.0, -170.0, 190.0),
        (-170.0, 170.0, -190.0),
        (355.0, 350.0, 350.0),
        (0.0, 10.0, 10.0),
        (0.0, -10.0, -10.0),
    ],
)
def test_unwrap_angle_keeps_continuity(previous: float, raw: float, expected: float) -> None:
    assert unwrap_angle_deg(previous, raw) == pytest.approx(expected)

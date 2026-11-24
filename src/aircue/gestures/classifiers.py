"""Static pose classifiers. They return booleans and never emit events or commands."""

from __future__ import annotations

from aircue.vision.geometry import joint_angle_deg, usable_landmarks
from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    THUMB_MCP,
    THUMB_TIP,
    HandRecord,
)

_OPEN_PALM = (True, True, True, True, True)
_FIST = (False, False, False, False, False)
_PEACE = (False, True, True, False, False)
_SHAKA = (True, False, False, False, True)
_THUMBS_UP = (True, False, False, False, False)
_POINTER = (True, True, False, False, False)
# Pointing bends the PIP joint more than the synthetic straight pose assumes.
_POINTER_INDEX_TOLERANCE_DEG = 15.0
# In 3D a natural point-at-the-camera hooks to ~109-128 degrees; thumbs-up is ~72-85.
_POINTER_INDEX_3D_MIN_DEG = 100.0


def is_fist(hand: HandRecord) -> bool:
    return _matches(hand, _FIST)


def is_open_palm(hand: HandRecord) -> bool:
    return _matches(hand, _OPEN_PALM)


def is_peace(hand: HandRecord) -> bool:
    return _matches(hand, _PEACE)


def is_shaka(hand: HandRecord) -> bool:
    return _matches(hand, _SHAKA)


def is_thumbs_up(hand: HandRecord) -> bool:
    return _matches(hand, _THUMBS_UP) and _thumb_points_up(hand)


def is_pinch(hand: HandRecord, close_threshold: float = 0.22) -> bool:
    distance = hand.features.pinch_distance
    return distance is not None and distance < close_threshold


def is_pointer_pose(
    hand: HandRecord,
    min_separation: float = 0.40,
    extended_angle_deg: float = 160.0,
) -> bool:
    distance = hand.features.pinch_distance
    if distance is None or distance <= min_separation:
        return False
    extensions = hand.features.finger_extension
    if len(extensions) != len(_POINTER):
        return False
    thumb, _, middle, ring, little = extensions
    return (
        thumb is True
        and middle is False
        and ring is False
        and little is False
        and _index_points(hand, extended_angle_deg)
    )


def _index_points(hand: HandRecord, extended_angle_deg: float) -> bool:
    usable = usable_landmarks(hand.landmarks, hand.valid)
    mcp = usable.get(INDEX_MCP)
    pip = usable.get(INDEX_PIP)
    tip = usable.get(INDEX_TIP)
    if mcp is None or pip is None or tip is None:
        return False
    if hand.features.index_angle_3d_deg is not None:
        return hand.features.index_angle_3d_deg >= _POINTER_INDEX_3D_MIN_DEG
    threshold = extended_angle_deg - _POINTER_INDEX_TOLERANCE_DEG
    return joint_angle_deg(pip, mcp, tip) >= threshold


def _matches(hand: HandRecord, pattern: tuple[bool, ...]) -> bool:
    extensions = hand.features.finger_extension
    if len(extensions) != len(pattern):
        return False
    return all(extended is expected for extended, expected in zip(extensions, pattern, strict=True))


def _thumb_points_up(hand: HandRecord) -> bool:
    usable = usable_landmarks(hand.landmarks, hand.valid)
    mcp = usable.get(THUMB_MCP)
    tip = usable.get(THUMB_TIP)
    if mcp is None or tip is None:
        return False
    dx = tip.x - mcp.x
    dy = tip.y - mcp.y
    return dy < 0 and abs(dx) <= abs(dy) + 1e-9

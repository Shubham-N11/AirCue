"""Static pose classifiers. They return booleans and never emit events or commands."""

from __future__ import annotations

from aircue.vision.geometry import usable_landmarks
from aircue.vision.types import THUMB_MCP, THUMB_TIP, HandRecord

_OPEN_PALM = (True, True, True, True, True)
_FIST = (False, False, False, False, False)
_PEACE = (False, True, True, False, False)
_SHAKA = (True, False, False, False, True)
_THUMBS_UP = (True, False, False, False, False)
_POINTER = (True, True, False, False, False)


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


def is_pointer_pose(hand: HandRecord, min_separation: float = 0.40) -> bool:
    distance = hand.features.pinch_distance
    return _matches(hand, _POINTER) and distance is not None and distance > min_separation


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

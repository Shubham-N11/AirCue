"""Pure landmark geometry shared by feature extraction and gesture recognition."""

from __future__ import annotations

import math
from collections.abc import Sequence

from aircue.vision.types import (
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_MCP,
    PINKY_PIP,
    PINKY_TIP,
    RING_MCP,
    RING_PIP,
    RING_TIP,
    THUMB_CMC,
    THUMB_IP,
    THUMB_MCP,
    THUMB_TIP,
    WRIST,
    Landmark,
)

_FINGER_JOINTS = (
    (THUMB_MCP, THUMB_IP, THUMB_TIP),
    (INDEX_MCP, INDEX_PIP, INDEX_TIP),
    (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP),
    (RING_MCP, RING_PIP, RING_TIP),
    (PINKY_MCP, PINKY_PIP, PINKY_TIP),
)
_THUMB_MCP_JOINTS = (THUMB_CMC, THUMB_MCP, THUMB_IP)
_THUMB_EXTENSION_TOLERANCE_DEG = 20.0


def usable_landmarks(
    landmarks: Sequence[Landmark | None], valid: Sequence[bool]
) -> dict[int, Landmark]:
    """Return the landmarks that are present and marked valid."""
    if len(landmarks) != len(valid):
        raise ValueError("landmarks and validity must have the same length")
    return {
        index: landmark
        for index, (landmark, is_valid) in enumerate(zip(landmarks, valid, strict=True))
        if is_valid and landmark is not None
    }


def palm_scale(landmarks: Sequence[Landmark | None], valid: Sequence[bool]) -> float | None:
    """Wrist-to-middle-MCP distance, or None when either point is unavailable."""
    usable = usable_landmarks(landmarks, valid)
    wrist = usable.get(WRIST)
    middle = usable.get(MIDDLE_MCP)
    if wrist is None or middle is None:
        return None
    scale = math.hypot(middle.x - wrist.x, middle.y - wrist.y)
    return scale if scale > 0 else None


def wrist_angle(landmarks: Sequence[Landmark | None], valid: Sequence[bool]) -> float | None:
    """Image-space wrist angle in degrees; zero points the middle MCP straight up."""
    usable = usable_landmarks(landmarks, valid)
    wrist = usable.get(WRIST)
    middle = usable.get(MIDDLE_MCP)
    if wrist is None or middle is None:
        return None
    return math.degrees(math.atan2(middle.x - wrist.x, wrist.y - middle.y))


def pinch_distance(landmarks: Sequence[Landmark | None], valid: Sequence[bool]) -> float | None:
    """Thumb-tip to index-tip distance divided by palm scale."""
    usable = usable_landmarks(landmarks, valid)
    thumb = usable.get(THUMB_TIP)
    index = usable.get(INDEX_TIP)
    scale = palm_scale(landmarks, valid)
    if thumb is None or index is None or scale is None:
        return None
    return math.hypot(thumb.x - index.x, thumb.y - index.y) / scale


def finger_extension(
    landmarks: Sequence[Landmark | None],
    valid: Sequence[bool],
    threshold_deg: float = 160.0,
) -> tuple[bool | None, ...]:
    """Extension state for thumb, index, middle, ring, and little."""
    usable = usable_landmarks(landmarks, valid)
    thumb = _thumb_extended(usable, threshold_deg)
    return (thumb,) + tuple(
        _finger_extended(usable, joints, threshold_deg)
        for joints in _FINGER_JOINTS[1:]
    )


def hand_openness(extensions: Sequence[bool | None]) -> float | None:
    """Fraction of extended fingers, or None when any finger state is unknown."""
    if not extensions or any(extended is None for extended in extensions):
        return None
    return sum(1 for extended in extensions if extended) / len(extensions)


def joint_angle_deg(vertex: Landmark, first: Landmark, second: Landmark) -> float:
    """Angle at ``vertex`` between the rays to ``first`` and ``second``."""
    ax, ay = first.x - vertex.x, first.y - vertex.y
    bx, by = second.x - vertex.x, second.y - vertex.y
    norm = math.hypot(ax, ay) * math.hypot(bx, by)
    if norm == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / norm))
    return math.degrees(math.acos(cosine))


def joint_angle_3d_deg(vertex: Landmark, first: Landmark, second: Landmark) -> float:
    """Angle at ``vertex`` using all three metric coordinates."""
    ax, ay, az = first.x - vertex.x, first.y - vertex.y, first.z - vertex.z
    bx, by, bz = second.x - vertex.x, second.y - vertex.y, second.z - vertex.z
    norm = math.sqrt(ax * ax + ay * ay + az * az) * math.sqrt(bx * bx + by * by + bz * bz)
    if norm == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by + az * bz) / norm))
    return math.degrees(math.acos(cosine))


def _thumb_extended(
    landmarks: dict[int, Landmark], threshold_deg: float
) -> bool | None:
    """Both thumb joints must stay within a relaxed threshold.

    The thumb's two joints read noisier than a long finger's single joint, so the
    worst of the two is allowed 20 degrees more bend. Requiring both still rejects
    a thumb folded at either joint.
    """
    ip = _joint_angle(landmarks, _FINGER_JOINTS[0])
    mcp = _joint_angle(landmarks, _THUMB_MCP_JOINTS)
    if ip is None or mcp is None:
        return None
    return min(ip, mcp) >= threshold_deg - _THUMB_EXTENSION_TOLERANCE_DEG


def _joint_angle(
    landmarks: dict[int, Landmark], joints: tuple[int, int, int]
) -> float | None:
    base, middle, tip = (landmarks.get(index) for index in joints)
    if base is None or middle is None or tip is None:
        return None
    return joint_angle_deg(middle, base, tip)


def _finger_extended(
    landmarks: dict[int, Landmark],
    joints: tuple[int, int, int],
    threshold_deg: float,
) -> bool | None:
    angle = _joint_angle(landmarks, joints)
    return None if angle is None else angle >= threshold_deg

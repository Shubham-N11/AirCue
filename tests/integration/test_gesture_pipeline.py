"""End-to-end gesture tests from synthetic landmarks to semantic events."""

from __future__ import annotations

import ast
import math
import random
from pathlib import Path

import pytest

from aircue.config.schema import Config
from aircue.gestures.classifiers import is_pointer_pose
from aircue.gestures.recognizer import GestureRecognizer
from aircue.gestures.semantic import GestureAction, SemanticEvent
from aircue.gestures.vocabulary import GESTURES, Gesture
from aircue.presentation.target import TargetKind
from aircue.state.activation import ActivationController, ActivationSource
from aircue.state.states import InteractionState
from aircue.state.transitions import TransitionTrigger
from aircue.vision.features import extract_hand_record
from aircue.vision.types import (
    INDEX_PIP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_PIP,
    MIDDLE_TIP,
    PINKY_PIP,
    PINKY_TIP,
    RING_PIP,
    RING_TIP,
    THUMB_CMC,
    THUMB_IP,
    THUMB_MCP,
    THUMB_TIP,
    HandObservation,
    HandRecord,
    Landmark,
)
from tests.fixtures.landmarks import BASE_POSE, make_landmarks

FINGER_JOINTS = {
    "thumb": (THUMB_MCP, THUMB_IP, THUMB_TIP),
    "index": (5, INDEX_PIP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP),
    "ring": (13, RING_PIP, RING_TIP),
    "pinky": (17, PINKY_PIP, PINKY_TIP),
}
WRIST = 0


def ms(value: int) -> int:
    return value * 1_000_000


def curled_tip(mcp: int, pip: int, *, length: float = 0.08) -> tuple[float, float, float, float]:
    mcp_x, mcp_y, _ = BASE_POSE[mcp]
    pip_x, pip_y, _ = BASE_POSE[pip]
    dx, dy = mcp_x - pip_x, mcp_y - pip_y
    norm = math.hypot(dx, dy)
    return (pip_x + dx / norm * length, pip_y + dy / norm * length, 0.0, 0.9)


def pose_overrides(
    *,
    curled: tuple[str, ...] = (),
    thumb_up: bool = False,
    pinch: bool = False,
    pointer: bool = False,
) -> dict[int, tuple[float, float, float, float]]:
    overrides = {FINGER_JOINTS[name][2]: curled_tip(*FINGER_JOINTS[name][:2]) for name in curled}
    if thumb_up:
        overrides[THUMB_CMC] = (0.36, 0.69, 0.0, 0.9)
        overrides[THUMB_IP] = (0.36, 0.55, 0.0, 0.9)
        overrides[THUMB_TIP] = (0.36, 0.45, 0.0, 0.9)
    if pinch:
        overrides[THUMB_TIP] = BASE_POSE[INDEX_TIP][:2] + (0.0, 0.9)
    if pointer:
        overrides[THUMB_CMC] = (0.33, 0.67, 0.0, 0.9)
        overrides[THUMB_IP] = (0.40, 0.55, 0.0, 0.9)
        overrides[THUMB_TIP] = (0.4727, 0.4227, 0.0, 0.9)
    return overrides


def rotate(landmarks: tuple[Landmark, ...], angle_deg: float) -> tuple[Landmark, ...]:
    """Rotate around the wrist; positive is clockwise from the user's perspective."""
    wx, wy = BASE_POSE[WRIST][:2]
    radians = math.radians(angle_deg)
    cosine, sine = math.cos(radians), math.sin(radians)
    rotated = []
    for landmark in landmarks:
        ux = landmark.x - wx
        uy = -(landmark.y - wy)
        rotated.append(
            Landmark(
                wx + ux * cosine - uy * sine,
                wy - (ux * sine + uy * cosine),
                landmark.z,
                landmark.confidence,
            )
        )
    return tuple(rotated)


def record(
    *,
    curled: tuple[str, ...] = (),
    thumb_up: bool = False,
    pinch: bool = False,
    pointer: bool = False,
    rotation_deg: float = 0.0,
    confidence: float = 0.9,
) -> HandRecord:
    landmarks = make_landmarks(
        pose_overrides(curled=curled, thumb_up=thumb_up, pinch=pinch, pointer=pointer),
        confidence=confidence,
    )
    if rotation_deg:
        landmarks = rotate(landmarks, rotation_deg)
    return extract_hand_record(
        HandObservation(
            track_id=0,
            landmarks=landmarks,
            confidence=confidence,
            handedness="Right",
        ),
        confidence_threshold=0.5,
        finger_extended_angle_deg=160.0,
    )


def drive(
    subject: GestureRecognizer,
    state: InteractionState,
    frames: list[tuple[int, HandRecord]],
) -> list[SemanticEvent]:
    events = []
    for sequence, (timestamp_ms, hand) in enumerate(frames, start=1):
        event = subject.update(hand, state, ms(timestamp_ms), sequence=sequence)
        if event is not None:
            events.append(event)
    return events


def test_fist_drives_pause_tracking() -> None:
    subject = GestureRecognizer(Config())
    events = drive(
        subject,
        InteractionState.ACTIVE,
        [
            (0, record(curled=("thumb", "index", "middle", "ring", "pinky"))),
            (100, record(curled=("thumb", "index", "middle", "ring", "pinky"))),
            (200, record(curled=("thumb", "index", "middle", "ring", "pinky"))),
        ],
    )
    assert len(events) == 1
    assert events[0].action is GestureAction.PAUSE_TRACKING
    assert events[0].gesture is Gesture.FIST
    assert events[0].onset_sequence == 1


def test_thumbs_up_drives_activation_and_resume() -> None:
    idle = GestureRecognizer(Config())
    idle_events = drive(
        idle,
        InteractionState.IDLE,
        [
            (0, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
            (400, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
            (800, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
        ],
    )
    assert [event.action for event in idle_events] == [GestureAction.ACTIVATE]
    assert idle_events[0].gesture is Gesture.THUMBS_UP

    paused = GestureRecognizer(Config())
    paused_events = drive(
        paused,
        InteractionState.PAUSED,
        [
            (0, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
            (125, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
            (250, record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)),
        ],
    )
    assert [event.action for event in paused_events] == [GestureAction.RESUME_TRACKING]


def test_peace_drives_scroll_entry_and_exit() -> None:
    active = GestureRecognizer(Config())
    entry = drive(
        active,
        InteractionState.ACTIVE,
        [
            (0, record(curled=("thumb", "ring", "pinky"))),
            (125, record(curled=("thumb", "ring", "pinky"))),
            (250, record(curled=("thumb", "ring", "pinky"))),
        ],
    )
    assert [event.action for event in entry] == [GestureAction.ENTER_SCROLL_MODE]
    assert entry[0].gesture is Gesture.PEACE

    scrolling = GestureRecognizer(Config())
    exit_events = drive(
        scrolling,
        InteractionState.SCROLL_MODE,
        [
            (0, record(curled=("thumb", "ring", "pinky"))),
            (125, record(curled=("thumb", "ring", "pinky"))),
            (250, record(curled=("thumb", "ring", "pinky"))),
        ],
    )
    assert [event.action for event in exit_events] == [GestureAction.EXIT_SCROLL_MODE]


def test_shaka_drives_exit_request() -> None:
    subject = GestureRecognizer(Config())
    frames = [
        (0, record(curled=("index", "middle", "ring"), thumb_up=True)),
        (750, record(curled=("index", "middle", "ring"), thumb_up=True)),
        (1500, record(curled=("index", "middle", "ring"), thumb_up=True)),
    ]
    events = drive(subject, InteractionState.IDLE, frames)
    assert [event.action for event in events] == [GestureAction.EXIT_REQUEST]
    assert events[0].gesture is Gesture.SHAKA


def test_pinch_drives_pointer_entry_and_click_candidate() -> None:
    subject = GestureRecognizer(Config())
    entry = drive(
        subject,
        InteractionState.ACTIVE,
        [(0, record(pinch=True)), (100, record(pinch=True))],
    )
    assert [event.action for event in entry] == [GestureAction.ENTER_POINTER_MODE]
    assert entry[0].gesture is Gesture.PINCH

    click = GestureRecognizer(Config())
    events = drive(
        click,
        InteractionState.POINTER_MODE,
        [(0, record(pinch=True)), (100, record(pinch=True)), (200, record()), (300, record())],
    )
    assert [event.action for event in events] == [GestureAction.CLICK_CANDIDATE]
    assert events[0].gesture is Gesture.PINCH_RELEASE
    assert events[0].onset_sequence == 3


def test_long_pinch_drives_pointer_exit() -> None:
    subject = GestureRecognizer(Config())
    events = drive(
        subject,
        InteractionState.POINTER_MODE,
        [(0, record(pinch=True)), (100, record(pinch=True)), (800, record(pinch=True))],
    )
    assert [event.action for event in events] == [GestureAction.EXIT_POINTER_MODE]
    assert events[0].gesture is Gesture.PINCH


def test_open_palm_rotation_drives_slide_navigation() -> None:
    clockwise = GestureRecognizer(Config())
    events = drive(
        clockwise,
        InteractionState.ACTIVE,
        [(0, record()), (100, record(rotation_deg=30.0))],
    )
    assert [event.action for event in events] == [GestureAction.NEXT_SLIDE]
    assert events[0].gesture is Gesture.OPEN_PALM_CLOCKWISE

    counterclockwise = GestureRecognizer(Config())
    events = drive(
        counterclockwise,
        InteractionState.ACTIVE,
        [(0, record()), (100, record(rotation_deg=-30.0))],
    )
    assert [event.action for event in events] == [GestureAction.PREV_SLIDE]
    assert events[0].gesture is Gesture.OPEN_PALM_COUNTERCLOCKWISE


def test_pointer_pose_is_valid_but_emits_no_click_or_mode_event() -> None:
    subject = GestureRecognizer(Config())
    frames = [
        (timestamp, record(curled=("middle", "ring", "pinky"), pointer=True))
        for timestamp in range(0, 1000, 100)
    ]
    assert drive(subject, InteractionState.POINTER_MODE, frames) == []


def test_every_vocabulary_gesture_is_reachable_end_to_end() -> None:
    fist = record(curled=("thumb", "index", "middle", "ring", "pinky"))
    thumbs_up = record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)
    peace = record(curled=("thumb", "ring", "pinky"))
    shaka = record(curled=("index", "middle", "ring"), thumb_up=True)
    pinch = record(pinch=True)
    release = record()
    pointer = record(curled=("middle", "ring", "pinky"), pointer=True)

    observed = set()
    for state, frames in [
        (InteractionState.ACTIVE, [(0, fist), (200, fist)]),
        (InteractionState.IDLE, [(0, thumbs_up), (800, thumbs_up)]),
        (InteractionState.ACTIVE, [(0, peace), (250, peace)]),
        (InteractionState.IDLE, [(0, shaka), (1500, shaka)]),
        (InteractionState.ACTIVE, [(0, pinch), (100, pinch)]),
        (InteractionState.POINTER_MODE, [(0, pinch), (100, pinch), (200, release), (300, release)]),
        (InteractionState.ACTIVE, [(0, record()), (100, record(rotation_deg=30.0))]),
        (InteractionState.ACTIVE, [(0, record()), (100, record(rotation_deg=-30.0))]),
    ]:
        subject = GestureRecognizer(Config())
        for event in drive(subject, state, frames):
            observed.add(event.gesture)

    # The pointer pose is movement input, so it has no semantic event here.
    assert is_pointer_pose(pointer) is True
    assert observed == set(GESTURES) - {Gesture.POINTER_POSE}


def test_vocabulary_is_exactly_the_nine_configured_gestures() -> None:
    assert len(GESTURES) == 9
    assert set(GESTURES) == {
        Gesture.OPEN_PALM_CLOCKWISE,
        Gesture.OPEN_PALM_COUNTERCLOCKWISE,
        Gesture.FIST,
        Gesture.THUMBS_UP,
        Gesture.PINCH,
        Gesture.POINTER_POSE,
        Gesture.PINCH_RELEASE,
        Gesture.PEACE,
        Gesture.SHAKA,
    }


def test_no_pose_sequence_emits_outside_the_vocabulary() -> None:
    randomizer = random.Random(20261116)
    fingers = ("thumb", "index", "middle", "ring", "pinky")
    subject = GestureRecognizer(Config())
    vocabulary = set(GESTURES)
    states = list(InteractionState)
    for sequence in range(1, 501):
        curled = tuple(name for name in fingers if randomizer.random() < 0.5)
        hand = record(
            curled=curled,
            thumb_up=randomizer.random() < 0.3,
            pinch=randomizer.random() < 0.3,
            rotation_deg=randomizer.choice([-40.0, -20.0, 0.0, 20.0, 40.0]),
            confidence=randomizer.choice([0.4, 0.9]),
        )
        event = subject.update(
            hand,
            randomizer.choice(states),
            sequence * 33_000_000,
            sequence=sequence,
        )
        if event is not None:
            assert event.gesture in vocabulary
            assert isinstance(event.onset_sequence, int)
            assert event.confidence >= 0.0


def _gesture_sources() -> list[Path]:
    root = Path(__file__).parents[2] / "src" / "aircue"
    files = sorted((root / "gestures").glob("*.py"))
    files.append(root / "state" / "states.py")
    return files


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_gesture_layer_cannot_reach_presentation_or_input() -> None:
    forbidden = (
        "aircue.presentation",
        "aircue.commands",
        "aircue.dispatch",
        "aircue.app",
        "ctypes",
        "win32",
        "win32gui",
        "win32api",
        "subprocess",
        "pyautogui",
        "pynput",
    )
    for path in _gesture_sources():
        for module in _imported_modules(path):
            assert not any(
                module == prefix or module.startswith(prefix + ".") for prefix in forbidden
            ), f"{path.name} imports {module}"

    text = "\n".join(path.read_text(encoding="utf-8") for path in _gesture_sources())
    for call in ("SendInput", "SetCursorPos", "mouse_event", "keybd_event", "PostMessage"):
        assert call not in text


@pytest.mark.parametrize("module", ["recognizer", "semantic", "pinch", "rotation"])
def test_gesture_modules_import_only_domain_types(module: str) -> None:
    path = Path(__file__).parents[2] / "src" / "aircue" / "gestures" / f"{module}.py"
    allowed = (
        "aircue.config",
        "aircue.gestures",
        "aircue.state",
        "aircue.vision",
    )
    for imported in _imported_modules(path):
        if imported.startswith("aircue."):
            assert imported.startswith(allowed), f"{module}.py imports {imported}"


def test_hand_presence_alone_never_activates() -> None:
    subject = GestureRecognizer(Config())
    frames = [(timestamp, record()) for timestamp in range(0, 5_000, 100)]
    events = drive(subject, InteractionState.IDLE, frames)
    assert [event.action for event in events] == []


def test_thumbs_up_hold_drives_an_accepted_activation() -> None:
    subject = GestureRecognizer(Config())
    thumbs_up = record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)
    frames = [(0, thumbs_up), (799, thumbs_up), (800, thumbs_up)]
    events = drive(subject, InteractionState.IDLE, frames)
    assert [event.action for event in events] == [GestureAction.ACTIVATE]

    decision = ActivationController().evaluate(
        InteractionState.IDLE,
        TargetKind.NORMAL_SLIDESHOW,
        ActivationSource.GESTURE,
        target_ready=True,
    )
    assert decision.accepted is True
    assert decision.trigger is TransitionTrigger.ACTIVATION_CONFIRMED


def test_thumbs_up_hold_drives_an_accepted_resume() -> None:
    subject = GestureRecognizer(Config())
    thumbs_up = record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)
    frames = [(0, thumbs_up), (249, thumbs_up), (250, thumbs_up)]
    events = drive(subject, InteractionState.PAUSED, frames)
    assert [event.action for event in events] == [GestureAction.RESUME_TRACKING]

    decision = ActivationController().evaluate(
        InteractionState.PAUSED,
        TargetKind.PRESENTER_VIEW,
        ActivationSource.GESTURE,
        target_ready=True,
    )
    assert decision.accepted is True
    assert decision.trigger is TransitionTrigger.RESUME_CONFIRMED


def test_activation_is_rejected_for_edit_mode_after_a_valid_hold() -> None:
    subject = GestureRecognizer(Config())
    thumbs_up = record(curled=("index", "middle", "ring", "pinky"), thumb_up=True)
    events = drive(subject, InteractionState.IDLE, [(0, thumbs_up), (800, thumbs_up)])
    assert [event.action for event in events] == [GestureAction.ACTIVATE]

    decision = ActivationController().evaluate(
        InteractionState.IDLE,
        TargetKind.EDIT_MODE,
        ActivationSource.GESTURE,
        target_ready=True,
    )
    assert decision.accepted is False

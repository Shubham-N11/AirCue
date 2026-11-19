from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aircue.capture import Frame
from aircue.performance.timing import FrameTimings, Stage
from aircue.vision import MediaPipeHandTracker, TrackerError, TrackerInitializationError


class FakeLandmark:
    def __init__(self, index: int) -> None:
        self.x = index / 100
        self.y = index / 200
        self.z = 0.0


class FakeCategory:
    def __init__(self, name: str, score: float) -> None:
        self.category_name = name
        self.score = score


class FakeResult:
    def __init__(self, hands: list[list[FakeLandmark]], labels: list[list[FakeCategory]]) -> None:
        self.hand_landmarks = hands
        self.handedness = labels


class FakeLandmarker:
    def __init__(self, result: FakeResult | None = None, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.closed = False
        self.seen_image: Any = None

    def detect(self, image: Any) -> FakeResult:
        if self.fail or self.result is None:
            raise RuntimeError("inference failed")
        self.seen_image = image
        return self.result

    def close(self) -> None:
        self.closed = True


def frame() -> Frame:
    return Frame(np.zeros((360, 640, 3), dtype=np.uint8), 1, 1)


def hand(count: int = 21) -> list[FakeLandmark]:
    return [FakeLandmark(index) for index in range(count)]


def model_file(tmp_path: Path) -> str:
    path = tmp_path / "hand.task"
    path.write_bytes(b"placeholder")
    return str(path)


def test_valid_hand_returns_all_landmarks(tmp_path: Path) -> None:
    result = FakeResult([hand()], [[FakeCategory("Right", 0.91)]])
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(result)
    )
    observations = source.detect(frame())
    assert len(observations) == 1
    observation = observations[0]
    assert observation.track_id == 0
    assert observation.handedness == "Right"
    assert observation.confidence == pytest.approx(0.91)
    assert len(observation.landmarks) == 21
    assert observation.landmarks[0].x == 0.0
    assert observation.landmarks[10].x == pytest.approx(0.1)
    assert observation.landmarks[0].confidence == pytest.approx(0.91)


def test_no_hand_returns_empty(tmp_path: Path) -> None:
    source = MediaPipeHandTracker(
        model_file(tmp_path),
        landmarker_factory=lambda: FakeLandmarker(FakeResult([], [])),
    )
    assert source.detect(frame()) == ()


def test_multiple_hands_are_returned_with_separate_ids(tmp_path: Path) -> None:
    result = FakeResult(
        [hand(), hand()],
        [[FakeCategory("Left", 0.8)], [FakeCategory("Right", 0.9)]],
    )
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(result)
    )
    observations = source.detect(frame())
    assert [item.track_id for item in observations] == [0, 1]
    assert [item.handedness for item in observations] == ["Left", "Right"]


def test_low_confidence_hand_is_rejected(tmp_path: Path) -> None:
    result = FakeResult([hand()], [[FakeCategory("Left", 0.49)]])
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(result)
    )
    assert source.detect(frame()) == ()


def test_missing_model_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(TrackerInitializationError, match="not found"):
        MediaPipeHandTracker(str(tmp_path / "absent.task"))
    with pytest.raises(TrackerInitializationError, match="not configured"):
        MediaPipeHandTracker("")


def test_native_initialization_failure_is_wrapped(tmp_path: Path) -> None:
    def fail() -> FakeLandmarker:
        raise OSError("native load failure")

    with pytest.raises(TrackerInitializationError, match="failed to load"):
        MediaPipeHandTracker(model_file(tmp_path), landmarker_factory=fail)


def test_inference_failure_is_reported(tmp_path: Path) -> None:
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(fail=True)
    )
    with pytest.raises(TrackerError, match="tracking failed"):
        source.detect(frame())


def test_close_is_forwarded(tmp_path: Path) -> None:
    landmarker = FakeLandmarker(FakeResult([], []))
    source = MediaPipeHandTracker(model_file(tmp_path), landmarker_factory=lambda: landmarker)
    source.close()
    assert landmarker.closed is True


def test_instrumented_detection_records_ordered_stage_spans(tmp_path: Path) -> None:
    result = FakeResult([hand()], [[FakeCategory("Right", 0.91)]])
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(result)
    )
    timings = FrameTimings()

    source.detect(
        Frame(np.zeros((360, 640, 3), dtype=np.uint8), 1, 1, timings=timings)
    )

    assert [span.stage for span in timings.spans] == [
        Stage.PREPROCESSING,
        Stage.INFERENCE,
        Stage.LANDMARK_PROCESSING,
    ]
    assert all(span.clock == "perf" for span in timings.spans)
    assert all(span.end_ns >= span.start_ns for span in timings.spans)
    assert [span.start_ns for span in timings.spans] == sorted(
        span.start_ns for span in timings.spans
    )


def test_uninstrumented_detection_records_nothing(tmp_path: Path) -> None:
    result = FakeResult([hand()], [[FakeCategory("Right", 0.91)]])
    source = MediaPipeHandTracker(
        model_file(tmp_path), landmarker_factory=lambda: FakeLandmarker(result)
    )

    assert len(source.detect(frame())) == 1

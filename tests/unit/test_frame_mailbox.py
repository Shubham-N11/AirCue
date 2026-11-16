import threading
import time

import numpy as np

from aircue.capture import (
    CaptureFailureError,
    CaptureMode,
    CaptureOpenResult,
    Frame,
    FrameMailbox,
)
from aircue.capture.mailbox import CaptureThread


class CountingSource:
    def __init__(self) -> None:
        self.mode: CaptureMode | None = CaptureMode(640, 360, 30)
        self.read_count = 0
        self.fail = False

    def open(self, mode: CaptureMode) -> CaptureOpenResult:
        self.mode = mode
        return CaptureOpenResult(mode, mode, ())

    def read(self) -> Frame:
        if self.fail:
            raise CaptureFailureError("unplugged")
        self.read_count += 1
        return Frame(np.zeros((2, 2, 3), dtype=np.uint8), self.read_count, self.read_count)

    def close(self) -> None:
        self.mode = None


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_mailbox_keeps_only_newest_frame() -> None:
    mailbox = FrameMailbox()
    for sequence in range(1, 4):
        mailbox.publish(Frame(np.zeros((1, 1, 3), dtype=np.uint8), sequence, sequence))

    assert mailbox.depth == 1
    assert mailbox.dropped == 2
    newest = mailbox.take()
    assert newest is not None
    assert newest.sequence == 3
    assert mailbox.depth == 0


def test_mailbox_take_timeout_returns_none() -> None:
    mailbox = FrameMailbox()
    assert mailbox.take(timeout=0.01) is None


def test_mailbox_close_wakes_consumer() -> None:
    mailbox = FrameMailbox()
    threading.Timer(0.02, mailbox.close).start()
    started = time.monotonic()
    assert mailbox.take(timeout=1.0) is None
    assert time.monotonic() - started < 1.0


def test_capture_continues_while_consumer_is_blocked() -> None:
    source = CountingSource()
    mailbox = FrameMailbox()
    capture = CaptureThread(source, mailbox, retry_delay_s=0.0)
    capture.start()
    try:
        wait_for(lambda: source.read_count >= 20)
        assert capture.is_alive
        assert mailbox.depth <= 1
        assert mailbox.dropped > 0
    finally:
        assert capture.stop()


def test_capture_reports_errors_and_keeps_running() -> None:
    source = CountingSource()
    source.fail = True
    errors: list[CaptureFailureError] = []
    capture = CaptureThread(source, FrameMailbox(), on_error=errors.append, retry_delay_s=0.0)
    capture.start()
    try:
        wait_for(lambda: len(errors) >= 2)
        assert capture.is_alive
    finally:
        assert capture.stop()


def test_capture_stop_joins_thread() -> None:
    source = CountingSource()
    capture = CaptureThread(source, FrameMailbox(), retry_delay_s=0.0)
    capture.start()
    wait_for(lambda: source.read_count >= 1)
    assert capture.stop()
    assert not capture.is_alive

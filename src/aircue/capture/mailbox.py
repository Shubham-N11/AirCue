"""Single-slot frame mailbox and capture thread."""

from __future__ import annotations

import threading
from collections.abc import Callable

from aircue.capture.source import FrameSource
from aircue.capture.types import CaptureError, Frame


class FrameMailbox:
    """Holds at most one unconsumed frame; newer frames replace older ones."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._slot: Frame | None = None
        self._dropped = 0
        self._closed = False

    def publish(self, frame: Frame) -> None:
        with self._condition:
            if self._closed:
                return
            if self._slot is not None:
                self._dropped += 1
            self._slot = frame
            self._condition.notify()

    def take(self, timeout: float | None = None) -> Frame | None:
        with self._condition:
            if self._slot is None and not self._closed:
                self._condition.wait(timeout)
            frame = self._slot
            self._slot = None
            return frame

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    @property
    def depth(self) -> int:
        with self._condition:
            return 0 if self._slot is None else 1

    @property
    def dropped(self) -> int:
        with self._condition:
            return self._dropped


class CaptureThread:
    """Reads frames continuously and publishes them without blocking."""

    def __init__(
        self,
        source: FrameSource,
        mailbox: FrameMailbox,
        *,
        on_error: Callable[[CaptureError], None] | None = None,
        retry_delay_s: float = 0.05,
    ) -> None:
        self._source = source
        self._mailbox = mailbox
        self._on_error = on_error
        self._retry_delay_s = retry_delay_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frames_captured = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("capture thread is already started")
        self._thread = threading.Thread(target=self._run, name="aircue-capture", daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 1.0) -> bool:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(join_timeout)
            return not thread.is_alive()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._source.read()
            except CaptureError as exc:
                if self._on_error is not None:
                    self._on_error(exc)
                if self._retry_delay_s > 0:
                    self._stop.wait(self._retry_delay_s)
                continue
            self._frames_captured += 1
            self._mailbox.publish(frame)

    @property
    def frames_captured(self) -> int:
        return self._frames_captured

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

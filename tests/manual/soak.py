"""Manual 60-minute soak harness for task 9.6.

Run in an interactive terminal, perform normal gestures, then exit AirCue with
Ctrl+Alt+Q. The harness samples AirCue's memory, threads, and handles every few
seconds and writes a CSV plus a markdown summary under reports/.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPTHREAD = 0x4
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ThreadID", wt.DWORD),
        ("th32OwnerProcessID", wt.DWORD),
        ("tpBasePri", wt.LONG),
        ("tpDeltaPri", wt.LONG),
        ("dwFlags", wt.DWORD),
    ]


def _win32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    psapi.GetProcessMemoryInfo.argtypes = [
        wt.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wt.DWORD,
    ]
    return kernel32, psapi


def sample(pid: int) -> tuple[int, int, int] | None:
    """Return (working_set_bytes, threads, handles) or None if unavailable."""
    kernel32, psapi = _win32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        handle_count = wt.DWORD()
        if not kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count)):
            return None
        threads = 0
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snapshot and snapshot != INVALID_HANDLE_VALUE:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            if kernel32.Thread32First(snapshot, ctypes.byref(entry)):
                while True:
                    if entry.th32OwnerProcessID == pid:
                        threads += 1
                    if not kernel32.Thread32Next(snapshot, ctypes.byref(entry)):
                        break
            kernel32.CloseHandle(snapshot)
        return counters.WorkingSetSize, threads, handle_count.value
    finally:
        kernel32.CloseHandle(handle)


def summarize(
    stamp: str,
    command: list[str],
    samples: list[tuple[float, int, int, int | None, int | None, int | None]],
    duration_s: float,
    exit_code: int,
) -> str:
    valid = [value for value in samples if value[3] is not None]
    lines = [
        f"# Soak result {stamp}",
        "",
        f"- Command: `{' '.join(command)}`",
        f"- Duration: {duration_s / 60:.1f} minutes",
        f"- AirCue exit code: {exit_code}",
        f"- Samples: {len(samples)} ({len(samples) - len(valid)} unavailable)",
    ]
    if valid:
        memory = [value[3] / (1024 * 1024) for value in valid if value[3] is not None]
        threads = [value[4] for value in valid if value[4] is not None]
        handles = [value[5] for value in valid if value[5] is not None]
        lines += [
            f"- Working set MB: first {memory[0]:.1f}, last {memory[-1]:.1f}, "
            f"min {min(memory):.1f}, max {max(memory):.1f}",
            f"- Threads: first {threads[0]}, last {threads[-1]}, max {max(threads)}",
            f"- Handles: first {handles[0]}, last {handles[-1]}, max {max(handles)}",
        ]
    lines += [
        "",
        "Record gesture activity, camera mode, PowerPoint version, and display layout",
        "alongside these numbers. Interpretation is manual: flat memory, threads, and",
        "handles across the soak are the pass condition.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--config", help="passed to aircue run --config")
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("soak: Windows only", file=sys.stderr)
        return 2
    if args.self_check:
        values = [sample(os.getpid()) for _ in range(3)]
        if any(value is None or value[0] <= 0 or value[1] <= 0 for value in values):
            print("soak: self-check failed", file=sys.stderr)
            return 1
        print(f"soak: self-check ok {values[-1]}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = args.out / f"soak-{stamp}.csv"
    summary_path = args.out / f"soak-{stamp}.md"

    command = [sys.executable, "-m", "aircue", "run"]
    if args.config:
        command += ["--config", args.config]
    print("soak:", " ".join(command))
    child = subprocess.Popen(command)

    samples: list[tuple[float, int, int, int | None, int | None, int | None]] = []
    started = time.monotonic()
    milestone = args.minutes * 60
    announced = False
    try:
        while child.poll() is None:
            elapsed = time.monotonic() - started
            values = sample(child.pid)
            if values is None:
                samples.append((elapsed, child.pid, 0, None, None, None))
            else:
                samples.append((elapsed, child.pid, 0, *values))
            if not announced and elapsed >= milestone:
                announced = True
                print(
                    f"soak: {args.minutes:g} minutes reached; "
                    "press Ctrl+Alt+Q to exit AirCue"
                )
            time.sleep(max(0.05, args.interval))
    except KeyboardInterrupt:
        print("soak: interrupted; stop AirCue with Ctrl+Alt+Q", file=sys.stderr)

    exit_code = child.wait()
    duration_s = time.monotonic() - started

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["elapsed_s", "pid", "reserved", "working_set_bytes", "threads", "handles"]
        )
        writer.writerows(samples)

    summary = summarize(stamp, command, samples, duration_s, exit_code)
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"soak: CSV {csv_path}")
    print(f"soak: summary {summary_path}")
    if exit_code != 0:
        print("soak: AirCue did not exit cleanly", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

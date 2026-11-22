# AirCue

AirCue turns a standard laptop webcam into a hands-free PowerPoint controller.
A small set of deliberate hand gestures drives slide navigation, pause/resume,
a pointer, clicking, and scrolling without touching the keyboard or mouse.

AirCue is under active development. The behavioral contract, architecture,
performance targets, and reliability requirements live in
[`openspec/changes/establish-aircue-gesture-navigation`](openspec/changes/establish-aircue-gesture-navigation).

## Status

Pre-release. No performance or hardware-compatibility claim is verified until it
is recorded in the project's validation reports.

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.11 or newer
- A standard webcam
- Microsoft PowerPoint (2019, 2021, or Microsoft 365) for presentation control

v1 is CPU-only. A GPU backend is optional and not currently supported; see
[`docs/backend-decision.md`](docs/backend-decision.md).

## Quickstart

From a checkout of this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

1. Download the MediaPipe hand-landmark model (`hand_landmarker.task`) from the
   official source listed in
   [`docs/tracker-selection.md`](docs/tracker-selection.md). The model is not
   bundled.
2. Create `%APPDATA%\AirCue\config.json` with at least the model path:

   ```json
   {
     "vision": { "model_path": "C:\\path\\to\\hand_landmarker.task" }
   }
   ```

3. Open a PowerPoint slideshow so the slideshow window is foreground.
4. Check that AirCue can see the presentation target:

   ```powershell
   aircue diagnose
   ```

   The last line reports `target=normal_slideshow` or `target=presenter_view`
   with the available capabilities. `edit_mode` and `unknown` targets cannot be
   controlled.

5. Start AirCue and activate it with a thumbs-up hold or `Ctrl+Alt+A`:

   ```powershell
   aircue run
   ```

   `aircue run --config PATH` reads a configuration other than the default
   `%APPDATA%\AirCue\config.json`.

`aircue benchmark` is listed in `--help` but is not available in this build; it
exits with code 3.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean exit |
| 1 | Startup failed (camera, tracker, or adapter) |
| 2 | Invalid command line or configuration |
| 3 | Requested feature is not available in this build |

## Gestures

| Action | Gesture |
|---|---|
| Activate | Thumbs-up held 0.8 s in IDLE, or `Ctrl+Alt+A` |
| Resume | Thumbs-up held 0.25 s in PAUSED |
| Pause / deactivate | Fist held 0.2 s, or `Ctrl+Alt+D` |
| Next / previous slide | Rotate an open palm clockwise / counterclockwise |
| Enter pointer mode | Pinch in ACTIVE (the entry pinch is consumed) |
| Click | Pinch and release in POINTER_MODE |
| Double-click | Two pinch-release clicks within 350 ms |
| Leave pointer mode | Hold the pinch for 0.7 s |
| Enter / leave scroll mode | Peace sign held 0.25 s |
| Scroll | Move the hand up or down in SCROLL_MODE |
| Exit AirCue | Shaka held 1.5 s, or `Ctrl+Alt+Q` |

A single click is intentionally held for the 350 ms double-click window before
it is sent. Pointer, click, and scroll are unavailable in PowerPoint's Presenter
View; navigation still works there. Edit mode and unknown targets are refused.

## Configuration

The configuration file is JSON merged over the code defaults. Unknown keys,
wrong types, and out-of-range values are rejected at startup with exit code 2.
The defaults used most often:

```json
{
  "vision": { "model_path": "C:\\path\\to\\hand_landmarker.task" },
  "camera": { "device_index": 0 },
  "hotkeys": {
    "activate": "ctrl+alt+a",
    "deactivate": "ctrl+alt+d",
    "exit": "ctrl+alt+q"
  },
  "ui": { "overlay_enabled": true, "overlay_opacity": 0.85 },
  "diagnostics": { "log_level": "INFO" }
}
```

Hotkey strings use `ctrl`, `alt`, `shift`, and `win` modifiers plus one letter,
digit, or named key (`space`, `tab`, `enter`, `esc`).

Debug capture is off by default. When enabled, AirCue writes at most one JPEG
per second to the configured directory and records the opt-in in the session
log. A write failure disables capture and is logged; the session continues.

```json
{ "diagnostics": { "debug_capture": true, "debug_capture_dir": "C:\\path\\to\\frames" } }
```

## Troubleshooting

### Camera

`aircue run` reports `startup failed: camera: ...` when the camera cannot be
opened. Close applications that may hold the camera (Teams, Zoom, Camera), then
retry. If the wrong camera is selected, set `camera.device_index`. During a
session, a missing camera frame for 2 s moves AirCue to `ERROR` and stops input.
AirCue then makes three reconnect attempts with 500 ms backoff. If one succeeds,
it returns to `IDLE` and still requires deliberate activation; if all three fail,
fix the camera and restart AirCue.

### Permissions

Windows must allow desktop applications to use the camera: **Settings > Privacy
& security > Camera > Let desktop apps access your camera**. A corporate policy
that blocks camera access produces the same startup failure as a busy camera.
No image is recorded; frames stay in memory unless debug capture is explicitly
enabled.

### PowerPoint

AirCue controls only a running slideshow in **Normal Slideshow** or **Presenter
View**. Start the slideshow before activating. In edit mode the target is
`edit_mode` and activation is refused. Run `aircue diagnose` to see the detected
windows, target kind, and capabilities; when more than one candidate cannot be
resolved, the target is `unknown` and AirCue sends no input.

### Focus

Commands are sent only while the slideshow window is foreground. If PowerPoint
loses focus, AirCue pauses without sending input to the new foreground
application. Bring the slideshow back to the front and resume with a thumbs-up
hold. A click is rejected when the target is not foreground, even if the mode is
still active.

### Overlay

The status overlay is a 480 x 92 topmost bar at the top of the primary monitor.
It shows the state, target kind, capabilities, the activation/resume prompt, and
a fault reason. It never takes keyboard focus and is click-through, so it cannot
intercept a click from the pointer. Hide it with `"overlay_enabled": false` or
change its transparency with `overlay_opacity` (0.1 to 1.0).

### Logs

Session logs are JSON lines in `%LOCALAPPDATA%\AirCue\logs\aircue.jsonl` with
rotation. Each record carries a `session` identifier, `ts_ns` (monotonic
nanoseconds), `severity`, `event`, and, for gesture, state, dispatch, adapter,
and fault records, the `generation` that produced it. Logged fields include the
command sequence, elapsed time, and fault reason. Logs contain no camera images.

## Development setup

Run the checks:

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

## Documentation

- [Vision pipeline](docs/vision-pipeline.md)
- [Tracker selection](docs/tracker-selection.md)
- [PowerPoint validation matrix](openspec/changes/establish-aircue-gesture-navigation/PPT-MATRIX.md)

## License

AirCue is released under the [MIT License](LICENSE).

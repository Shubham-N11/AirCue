# Vision pipeline

This document describes the implemented Phase 2 vision path: camera capture, the
single-slot frame mailbox, the selected hand-landmark runtime, landmark validation,
feature extraction, primary-hand continuity, and presence/loss reporting.

Performance statements here are host-specific measurements, not Tier 1 approval.
Task 2.8 (representative Tier 1 latency) remains open.

## Camera capture

`OpenCvCameraSource` opens the configured device with the requested resolution and
frame rate. The requested mode comes from the active hardware profile: Tier 1 starts
at 640x360, Tier 2 and Tier 3 at 1280x720.

When the camera rejects the requested mode, the source tries fallback candidates in
this order:

1. The requested size at the requested rate.
2. The requested size at half the requested rate.
3. 75% of each dimension at the requested rate, then at half rate.
4. 50% of each dimension at the requested rate, then at half rate.
5. 320x240 at 15 fps.

Odd dimensions are rounded down to even values, with a 160x120 floor. For a
640x360@15 request the sequence is 640x360@15, 640x360@8, 480x270@15, 480x270@8,
320x180@15, 320x180@8, then 320x240@15.

The result reports the mode actually opened and whether a fallback was used. If the
requested mode is rejected but a fallback opens, that is a recoverable capture
configuration error. If no candidate opens, the source raises
`CaptureUnavailableError`, which the state layer maps to an initialization failure.

A read failure after a successful open raises `CaptureFailureError`. The capture
thread reports the error through its callback and retries after a short delay instead
of terminating. The runtime layer owns reconnect policy.

## Latest-frame processing

`FrameMailbox` holds at most one unconsumed frame. Publishing a newer frame replaces
the older one and increments the drop counter. A consumer that falls behind therefore
processes the newest frame rather than a growing backlog.

`CaptureThread` runs as a daemon thread, reads continuously, publishes without
blocking on processing, and stops through an event plus a bounded join. Frames carry
a monotonic capture timestamp and an increasing sequence number.

## Hand-landmark runtime

The selected runtime is MediaPipe Tasks `HandLandmarker` in `IMAGE` mode, with at most
two hands and the configured confidence threshold. `docs/tracker-selection.md`
records the selection evidence and the rejected alternatives.

- `IMAGE` mode is used because `VIDEO` mode measured roughly six times slower in the
  same build and does not expose a stable hand identity through the Tasks result.
- The model is not bundled. `vision.model_path` must point to a local
  `hand_landmarker.task` file.
- The adapter checks the path before calling MediaPipe. A missing model path can cause
  a native access violation instead of a Python exception, so preflight validation is
  mandatory.
- Initialization failures are wrapped in `TrackerInitializationError`; inference
  failures are wrapped in `TrackerError`.
- Each detection returns 21 normalized landmarks, handedness, a hand-level confidence,
  and a frame-local detection index. MediaPipe exposes confidence per hand, not per
  landmark, so every landmark currently carries the hand score.

The tracker does not assign stable identity. `PrimaryHandSelector` owns identity
continuity.

## Landmark validity and features

`aircue.vision.features` produces a `FrameRecord` containing the capture timestamp,
frame sequence, stage timestamps, the selected hand, the number of hands detected, and
the presence status.

- A frame with a non-finite or out-of-range coordinate raises
  `InvalidLandmarkFrameError` and is discarded.
- Missing or below-threshold landmarks are kept in the 21-slot tuple but marked
  invalid.
- Geometry that depends on an invalid landmark reports the feature as unavailable
  instead of substituting a value.
- Features are normalized, so the same pose at 640x360 and 1280x720 produces
  comparable values.

Implemented features:

| Feature | Definition |
|---|---|
| Wrist angle | `atan2` of the wrist-to-middle-MCP vector, in degrees |
| Pinch distance | Thumb-tip to index-tip distance divided by palm scale |
| Palm scale | Wrist-to-middle-MCP distance |
| Hand openness | Fraction of fingers extended |
| Finger extension | Joint angle at the PIP for thumb, index, middle, ring, and little |

The finger-extension threshold defaults to 160 degrees. All thresholds and windows
come from the validated configuration schema.

## Primary hand and identity continuity

`PrimaryHandSelector` chooses at most one hand per frame:

- At acquisition, it selects the most confident observation and assigns stable id 0.
- While tracking, a new observation matches the primary when it has the same
  handedness and its wrist is within `vision.primary_match_distance` (default 0.35 in
  normalized units) of the last wrist. The nearest match wins.
- A second hand that briefly reports a higher confidence does not take over while the
  primary still matches.
- If no observation matches, the switch window starts at the primary's last-seen
  timestamp. After `timing.primary_hand_switch_ms` (default 500 ms), the most
  confident visible hand becomes primary with a new stable id.
- A hand that returns inside the switch window keeps its identity. The first frame
  after the gap is marked `suppress_recognition`, and the next frame is eligible
  again.
- Every selection during a gap, including the switch frame, suppresses recognition,
  so no gesture event can be derived from frames spanning the transition.

## Presence and loss reporting

`PresenceReporter` reports presence or absence on every processed frame. During an
absence run it returns the monotonic timestamp of the first absent frame; when presence
returns it also returns the completed run's duration. The vision layer does not change
application state.

The state layer consumes this data with the interaction-state thresholds:

| Absence duration | Behavior |
|---|---|
| 0-300 ms | Freeze pointer, click, and scroll output; no state change |
| 300-1,000 ms | Keep output frozen; emit no gap command |
| Over 1,000 ms | Transition to IDLE from ACTIVE, POINTER_MODE, SCROLL_MODE, or PAUSED |

The state implementation lands in Phase 4; the timing data it needs already exists.

## Reproducible latency spike

`tests/performance/vision_spike.py` measures the selected tracker on one image. It
letterboxes the image to 640x360, warms up the runtime, and reports p50/p95 for
tracker detection, feature extraction, and combined recognition compute.

```powershell
python tests/performance/vision_spike.py `
  --model C:\path\to\hand_landmarker.task `
  --image C:\path\to\hands.jpg `
  --samples 100
```

The model and test image are not committed. `reports/` is gitignored, so redirect the
JSON there if a run should be kept locally:

```powershell
python tests/performance/vision_spike.py --model ... --image ... > reports\vision-spike.json
```

Compare only runs from the same host, with the same model hash, image, sample count,
and warm-up. The script prints host, runtime, model SHA-256, image dimensions, and
measurement fields so a report can be audited.

### Recorded results

Tracker-selection spike, 2026-11-15, on an Intel Core i7-14700HX (20 cores, 28
logical processors), Windows 11 build 26200, Python 3.14.2, MediaPipe 0.10.30,
640x360 letterboxed input:

| Mode | Hands | Samples | p50 ms | p95 ms |
|---|---|---|---|---|
| IMAGE | 2 | 30 | 19.387 | 20.452 |
| IMAGE | 1 | 30 | 13.759 | 14.166 |
| VIDEO | 2 | 100 | 124.383 | 134.759 |

A documented-command rerun on 2026-11-16 with the same model and image, 30 measured
samples and 20 warm-up frames, produced detect p50 19.817 ms / p95 21.365 ms, feature
p50 0.052 ms / p95 0.060 ms, and combined recognition compute p50 19.870 ms / p95
21.418 ms, with two hands detected. This confirms the procedure reproduces the
recorded range on the same host.

One earlier IMAGE-mode run measured p50 192.9 ms. The cause was not established and
the host was concurrently busy during at least one run. Treat spread across runs as
real until controlled Tier 1 measurement exists.

### Interpretation

- These numbers do not approve Tier 1. The test host is not Tier 1 hardware, so task
  2.8 remains open.
- The stable run is within the proposed 50 ms recognition-compute target, but that is
  a host-specific observation, not a product claim.
- `VIDEO` mode remains rejected for the adapter based on the measured slowdown and
  the lack of stable identity.
- ONNX Runtime remains the documented fallback. No ONNX hand-landmark model was
  integrated or measured, so the fallback is unvalidated.

## Known limits

- MediaPipe is a native wheel. A Python or wheel change can break loading; the
  dependency range is `>=0.10.30,<1.0`.
- Model redistribution terms are unverified. Do not bundle the model until that
  review is complete.
- No GPU path has been validated; v1 is CPU-only, as recorded in
  [`docs/backend-decision.md`](backend-decision.md).
- The tracker passes the captured frame as-is. Camera candidates preserve the
  requested aspect ratio except the 320x240 floor; detection quality at that floor is
  unverified. The spike harness letterboxes only its still image.
- Tier 1 latency and sustained reliability remain unverified until tasks 2.8 and 9.x.

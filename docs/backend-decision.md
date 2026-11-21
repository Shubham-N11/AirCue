# Backend decision: CPU-only for v1

Date: 2026-11-21

## Decision

AirCue ships CPU-only. No GPU backend is supported, bundled, or installed by
default. This is the documented CPU-only outcome allowed by design.md D8, not a
failed milestone.

## Evidence

- The core dependencies are `numpy`, `opencv-python`, and `mediapipe`; none of
  them adds a GPU runtime.
- The selected tracker is MediaPipe Tasks `HandLandmarker`, which runs through
  TensorFlow Lite XNNPACK on the CPU (`docs/tracker-selection.md`).
- ONNX Runtime was checked only as packaging evidence during tracker selection.
  Its installed build exposed CPU and Azure providers, not a validated GPU
  provider, and no ONNX hand-landmark model was integrated or measured.
- The 8.9 benchmark gate (`aircue.hardware.backend_gate`) exists and fails
  closed to CPU, but no production GPU candidate is registered with it. Its
  acceptance evidence comes from fake backends.
- No GPU spike was run, because there is no supported Windows GPU backend to
  measure. Recording an invented comparison would violate the project's
  evidence rule.

## What would change this

A future GPU path must supply a real probe for a supported Windows backend, for
example a MediaPipe GPU delegate or an ONNX Runtime GPU/DirectML provider with an
integrated hand-landmark model. It must pass the 8.9 gate against CPU on the same
host and workload:

- at least 10% lower median latency,
- no worse p95 latency,
- no worse failure rate,
- non-overlapping median confidence intervals.

Only then would a `gpu` optional dependency extra be added. The core install
stays CPU-only; GPU support is never a default dependency.

## Consequences

- Hardware hints, calibration, adaptive frequency, and resource ceilings remain
  tuned for CPU inference.
- A CPU-only result says nothing about per-device acceptance. Tier 1/2/3
  performance and the real-camera acceptance tasks remain open.
- Users do not need a discrete or integrated GPU to install AirCue.

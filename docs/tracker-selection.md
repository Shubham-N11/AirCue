# Tracker selection spike

Date: 2026-11-15

## Decision

Select **MediaPipe Tasks HandLandmarker** (`mediapipe.tasks.python.vision.HandLandmarker`)
in **IMAGE** mode as the hand-landmark runtime. Identity continuity is implemented by
AirCue rather than by the runtime's VIDEO tracking path.

ONNX Runtime is not selected. It remains the documented fallback if the MediaPipe
adapter fails the Tier 1 latency or reliability gate in task 2.8. No ONNX hand-landmark
model was integrated or measured in this spike; ONNX Runtime packaging alone was checked.

This is a runtime-selection approval, not a hardware-performance approval. The host used
here is an Intel Core i7-14700HX laptop, which is not representative of Tier 1 hardware.

## Environment

| Item | Value |
|---|---|
| OS | Windows 11 build 26200 |
| CPU | Intel Core i7-14700HX, 20 cores / 28 logical processors |
| Python | 3.14.2 |
| MediaPipe | 0.10.30 |
| ONNX Runtime | 1.30.0 (`CPUExecutionProvider`, `AzureExecutionProvider`) |
| Model | `hand_landmarker.task`, float16, v1 |
| Model source | `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task` |
| Model SHA-256 | `FBC2A30080C3C557093B5DDFC334698132EB341044CCEE322CCF8BCF3607CDE1` |
| Test image | `woman_hands.jpg` from the MediaPipe tasks sample assets, letterboxed to 640x360 |

The model and image were downloaded to a temporary directory for this spike. Neither is
committed. The project must verify redistribution terms for any model asset it ships; do
not bundle this file until that review is complete.

## Packaging evidence

- `mediapipe 0.10.30` installs and imports on Windows, Python 3.14.2.
- `mediapipe.tasks.python.vision.HandLandmarker` creates a landmarker from the model file.
- The runtime uses TensorFlow Lite XNNPACK on CPU (`CPUExecutionProvider` equivalent).
- `onnxruntime 1.30.0` imports and reports its CPU provider on the same host.

Initialization failure was probed with a nonexistent model path. The call raised
`OSError: exception: access violation reading ...` from native code instead of a clean
Python exception. This is a runtime hazard: AirCue must validate the model path and file
before calling MediaPipe, and must treat any native initialization failure as fatal
without retrying it in-process.

## Output evidence

On the 640x960 source image, IMAGE mode returned two hands with 21 landmarks each and
handedness scores 0.936 and 0.962. On the letterboxed 640x360 frame, it returned two
hands with 21 landmarks each and a minimum handedness score of 0.956. A direct
non-aspect-preserving resize to 640x360 returned no hands, so preprocessing must preserve
aspect ratio (letterbox or crop), not squash the frame.

## Latency evidence

Measured with `perf_counter_ns` around `detect` / `detect_for_video`, after warm-up, on
the 640x360 letterboxed frame:

| Mode | Hands configured | Samples | p50 ms | p95 ms |
|---|---|---|---|---|
| IMAGE | 2 | 30 | 19.387 | 20.452 |
| IMAGE | 1 | 30 | 13.759 | 14.166 |
| VIDEO | 2 | 100 | 124.383 | 134.759 |

Two IMAGE-mode runs outside the final controlled sequence measured p50 192.9 ms and
p50 20.9 ms. The cause of that spread was not established; the host was concurrently
busy during at least one run. The stable sequence above was run at 5% reported CPU load.
No thermal or power instrumentation was recorded.

The IMAGE-mode result is within the proposed 50 ms baseline recognition-compute target
on this host, but this host is not a Tier 1 machine. Tier 1 acceptance requires the
controlled measurement in task 2.8. Do not reuse these numbers as a Tier 1 claim.

VIDEO mode was rejected for the adapter because it was roughly six times slower in this
build and MediaPipe does not expose a stable hand identity through the Tasks result.
AirCue assigns identity from landmark continuity and the configured primary-hand switch
window.

## Reproduction

The spike scripts are one-off manual tools and are not part of the repository. To repeat:
download the model and sample image, letterbox the image to 640x360, create a
`HandLandmarker` with `RunningMode.IMAGE` and `num_hands=2`, warm up, and time 30 calls
with `time.perf_counter_ns`. Treat these results as host-specific.

## Residual risks

- MediaPipe 0.10.30 is installed on Python 3.14; the dependency range is
  `>=0.10.30,<1.0`. A future Python or wheel change can break native loading.
- The native initialization path can access-violate on an invalid model path; preflight
  validation is mandatory.
- IMAGE mode gives no runtime tracking identity; AirCue owns identity continuity.
- Tier 1 latency and reliability remain unverified until task 2.8.
- Model asset redistribution terms remain unverified.

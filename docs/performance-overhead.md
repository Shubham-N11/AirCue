# Instrumentation overhead

Status: measured on one host with a synthetic replay workload. This is evidence
for the proposed 2 ms instrumentation-overhead target, not a live-camera or
inference-performance claim.

## Result

The proposed 2 ms target passed on this host.

| Measure | Value |
|---|---|
| Median enabled-minus-disabled delta | 0.021 ms |
| p95 enabled-minus-disabled delta | 1.025 ms |
| Pooled per-frame samples | 564,301 |
| Target | 2.0 ms |
| Result | Pass |

Block-level paired deltas (five 60 s blocks per condition):

| Block delta | Median | 95% CI of the mean |
|---|---|---|
| p50 | 0.004 ms | -0.079 to 0.050 ms |
| p95 | -0.066 ms | -0.638 to 0.194 ms |

The CIs cover zero. Host frequency scaling moved per-block p50 between roughly
0.20 ms and 0.59 ms across the ten blocks, so the p95 delta is the conservative
figure to compare with the target. The pooled p95 delta includes scheduling
tail noise; the block-level p95 deltas were negative in four of five pairs.

## Protocol

- Warm-up: 10 s per condition.
- Measurement: five 60 s blocks per condition, alternating enabled and
  disabled, with the starting condition flipped each pair.
- Timer: external `time.perf_counter_ns()` around each
  `process_frame()` + `tick()` iteration.
- Fixture: deterministic 8-frame 640x360 BGR fixture,
  SHA-256 `005a7fc443d8ceaa23f8463ceaa288c77d736af265951c134f6a647ed2e43df9`.
- Workload: `cv2.cvtColor` BGR-to-RGB and a 5x5 Gaussian blur on every frame,
  identical in both conditions. The tracker records the same stage spans as the
  real tracker; only instrumentation is toggled.
- Disabled blocks pass `timings=None`, so no spans or metrics are recorded. The
  external timer still measures every iteration.

Reproduce from the repository root (about 10.5 minutes):

```powershell
python tests/performance/instrumentation_overhead.py --json reports/instrumentation-overhead.json
```

`reports/` is gitignored; this document records the measured result.

## Environment

- Windows 11, build 10.0.26300
- Intel64 Family 6 Model 183 Stepping 1, 28 logical CPUs
- Python 3.14.2

## Limits

- The workload is synthetic. It measures instrumentation cost on the replay
  processing loop, not MediaPipe inference or a camera. It does not provide
  live-camera evidence and is not used for camera-to-action acceptance.
- The measurement is host-specific. Task 8.11 still requires the performance
  acceptance protocol on available Tier 1, Tier 2, and Tier 3 machines.
- The fixture is generated locally and is not a recorded human-hand sequence.
  No image data is committed.

# Design

## Context

AirCue is greenfield: the repository contains OpenSpec scaffolding and no application source, tests, commits, or benchmark data. The historical "277 passing tests" claim cannot be verified and is not used as evidence. The target is a Windows 10/11 laptop with a standard webcam, Python 3.11+, and Microsoft PowerPoint. Processing is local-only.

Constraints that shape the design:

- Baseline hardware is weak (Celeron, i3 U-series, Ryzen 3 U-series, 8 GB RAM, integrated graphics); the design must degrade rather than assume headroom.
- Gesture recognition must never execute presentation actions directly; validation belongs to the state/command layer.
- Activation must be deliberate, never inferred from hand presence alone.
- The presentation adapter must fail closed whenever it cannot confidently identify the intended PowerPoint target.
- GPU support is optional and must be justified by measured latency, not assumed.
- The repository must become GitHub-ready without importing undocumented behavior or unverified performance claims.
- See `proposal.md` for motivation and `specs/` for the behavioral contract. This document covers implementation strategy.

## Goals / Non-Goals

**Goals:**

- A deterministic, testable pipeline from camera frame to validated presentation command.
- One authoritative state transition table used by specs, code, and tests.
- Deliberate activation with visible feedback that never steals focus.
- Explicit pointer/pinch geometry and click arbitration.
- A bounded, ordered, cancellable command dispatch path with timeouts.
- Measurable per-stage, pipeline, dispatch, and gesture-response latency.
- Replay benchmarks separated from live-camera benchmarks.
- Fail-closed PowerPoint target identification across normal slideshow, Presenter View, extended displays, and multiple monitors.
- One codebase with configuration-driven hardware profiles and benchmark-gated backend selection.
- A test strategy that separates unit correctness from real-world recognition accuracy.

**Non-Goals:**

- Cross-platform support, cloud inference, or remote telemetry.
- Custom model training, a new hand-tracking model, or a learned gesture classifier.
- Presentation software other than PowerPoint.
- Pointer, click, or scroll control in Presenter View; v1 supports navigation only there.
- A general-purpose mouse replacement or multi-hand interaction.
- A settings UI in the first implementation; configuration is file-based.
- Guaranteed performance on every machine that meets a nominal hardware description.
- A license decision made on the owner's behalf.

## Decisions

### D1. Python 3.11+ with OpenCV and a pretrained hand-landmark runtime

Use Python 3.11+ for the application, OpenCV for camera capture and image handling, NumPy for geometry, and a pretrained hand-landmark runtime as the default tracker. MediaPipe Tasks is the first candidate because it provides 21 3D hand landmarks, runs on CPU, and requires no custom training. ONNX Runtime with a compatible hand-landmark model is the fallback if MediaPipe's Windows packaging or latency fails the Phase 2 spike.

**Alternatives considered:** C++/Rust would reduce overhead but raise development and review cost; a custom detector would require training data and violate the no-new-model constraint; a cloud service violates latency, privacy, and offline requirements.

**Consequences:** Python must not sit on the hot path for pixel processing. Inference stays inside native libraries that release the GIL; the application moves small landmark/feature objects between threads.

### D2. Geometric gesture classification, not a learned gesture model

Recognize the fixed vocabulary from landmark geometry and motion: finger extension angles, thumb-tip to index-tip distance normalized by palm size, hand openness, wrist angle, and temporal derivatives. This keeps behavior inspectable, testable with synthetic landmarks, and free of a training pipeline.

**Alternatives considered:** A trained classifier would need labeled data, add model risk, and make false-positive analysis harder for a nine-gesture vocabulary.

**Consequences:** Thresholds are explicit configuration, not learned weights. They must be calibrated with real users; the defaults in D10 are starting points, not claims.

### D3. Semantic events, deliberate activation, and one authoritative state machine

The recognizer emits semantic events such as `NEXT_SLIDE`, `PAUSE_TRACKING`, `RESUME_TRACKING`, `ACTIVATE`, `ENTER_POINTER_MODE`, `CLICK_CANDIDATE`, and `EXIT_REQUEST`. A single `CommandManager` validates each event against the current state and emits a command only when allowed. The recognizer has no reference to the presentation adapter.

Activation is never automatic. In `IDLE`, a deliberate thumbs-up hold of 800 ms or the activation hotkey (`Ctrl+Alt+A` by default) is required, and the presentation target must be confidently identified. Hand presence alone does nothing. A non-activating status overlay shows the current state, target kind, available capabilities, activation prompt in `IDLE`, resume prompt in `PAUSED`, and fault reason. It must never take foreground focus or intercept input.

The state machine uses an explicit transition table. `POINTER_MODE` and `SCROLL_MODE` are entered only from `ACTIVE` and exit only to `ACTIVE` (or to `PAUSED`, `IDLE`, `EXITING`, or `ERROR` on safety events). There is no direct pointer-to-scroll or scroll-to-pointer transition.

#### D3.1 Authoritative transition table

This table is the single source of truth. Specs, tests, and implementation must not define additional transitions.

| From | Trigger | To | Notes |
|---|---|---|---|
| `INITIALIZING` | initialization succeeds | `IDLE` | Camera, config, and adapter client ready |
| `INITIALIZING` | fatal initialization failure | `ERROR` | Report failing component |
| `INITIALIZING` | exit request | `EXITING` | Keyboard exit available during startup |
| `IDLE` | deliberate activation and valid target | `ACTIVE` | Thumbs-up 800 ms or activation hotkey |
| `IDLE` | tracking loss | `IDLE` | No commands; no state change |
| `IDLE` | presentation focus loss | `IDLE` | No commands; no state change |
| `IDLE` | deactivation hotkey | `IDLE` | No-op with feedback |
| `IDLE` | exit request | `EXITING` | Keyboard or sustained shaka |
| `IDLE` | unrecoverable fault | `ERROR` | |
| `ACTIVE` | fist confirmed | `PAUSED` | Cancel pending commands |
| `ACTIVE` | pinch confirmed | `POINTER_MODE` | Consumes the pinch; no click |
| `ACTIVE` | peace sign confirmed | `SCROLL_MODE` | |
| `ACTIVE` | tracking loss > 1,000 ms | `IDLE` | Cancel pending commands |
| `ACTIVE` | presentation focus loss | `PAUSED` | Immediate; cancel pending commands |
| `ACTIVE` | recoverable adapter error | `PAUSED` | Target/focus errors |
| `ACTIVE` | unrecoverable adapter error or timeout | `ERROR` | |
| `ACTIVE` | camera fault (no frame for 2,000 ms) | `ERROR` | Stop commands; bounded reconnect |
| `ACTIVE` | unrecoverable internal fault | `ERROR` | |
| `ACTIVE` | deactivation hotkey | `IDLE` | Cancel pending commands |
| `ACTIVE` | exit request | `EXITING` | |
| `PAUSED` | thumbs-up 250 ms with valid target and focus | `ACTIVE` | Otherwise stay `PAUSED` with feedback |
| `PAUSED` | tracking loss > 1,000 ms | `IDLE` | |
| `PAUSED` | deactivation hotkey | `IDLE` | |
| `PAUSED` | exit request | `EXITING` | |
| `PAUSED` | unrecoverable fault | `ERROR` | |
| `POINTER_MODE` | long pinch >= 700 ms | `ACTIVE` | Cancel pending click |
| `POINTER_MODE` | fist confirmed | `PAUSED` | Cancel pending click |
| `POINTER_MODE` | presentation focus loss | `PAUSED` | Cancel pending click |
| `POINTER_MODE` | tracking loss > 1,000 ms | `IDLE` | Cancel pending click |
| `POINTER_MODE` | recoverable adapter error | `PAUSED` | Cancel pending click |
| `POINTER_MODE` | unrecoverable adapter error or timeout | `ERROR` | |
| `POINTER_MODE` | camera fault (no frame for 2,000 ms) | `ERROR` | Cancel pending click; bounded reconnect |
| `POINTER_MODE` | unrecoverable internal fault | `ERROR` | Cancel pending click |
| `POINTER_MODE` | deactivation hotkey | `IDLE` | Cancel pending click |
| `POINTER_MODE` | exit request | `EXITING` | |
| `SCROLL_MODE` | peace sign confirmed | `ACTIVE` | Stop scroll output |
| `SCROLL_MODE` | fist confirmed | `PAUSED` | Stop scroll output |
| `SCROLL_MODE` | presentation focus loss | `PAUSED` | Stop scroll output |
| `SCROLL_MODE` | tracking loss > 1,000 ms | `IDLE` | Stop scroll output |
| `SCROLL_MODE` | recoverable adapter error | `PAUSED` | Stop scroll output |
| `SCROLL_MODE` | unrecoverable adapter error or timeout | `ERROR` | |
| `SCROLL_MODE` | camera fault (no frame for 2,000 ms) | `ERROR` | Stop scroll output; bounded reconnect |
| `SCROLL_MODE` | unrecoverable internal fault | `ERROR` | Stop scroll output |
| `SCROLL_MODE` | deactivation hotkey | `IDLE` | Stop scroll output |
| `SCROLL_MODE` | exit request | `EXITING` | |
| `ERROR` | explicit reinitialization succeeds | `IDLE` | Deliberate activation still required |
| `ERROR` | bounded camera reconnect succeeds after a camera fault | `IDLE` | Deliberate activation still required |
| `ERROR` | exit request | `EXITING` | Keyboard always; shaka if tracking is available |
| `EXITING` | cleanup completes | terminated | No further commands |

No other transition is permitted. In particular: no automatic `IDLE` to `ACTIVE`; no direct `POINTER_MODE` to `SCROLL_MODE` or reverse; no `ERROR` to `ACTIVE`; no `PAUSED` to a previous mode; no transition out of `EXITING`.

Tracking loss behavior:

- 0-300 ms: keep state, freeze pointer/scroll/click output, no new commands.
- 300-1,000 ms: keep state, outputs remain frozen, no command is generated from the gap.
- Over 1,000 ms: `ACTIVE`, `POINTER_MODE`, `SCROLL_MODE`, or `PAUSED` transitions to `IDLE`. `IDLE` remains `IDLE`; `ERROR` and `EXITING` are unaffected.
- After recovery, the user must re-arm gestures and, if the state is `IDLE`, deliberately activate. No command is replayed.

Focus loss behavior: `ACTIVE`, `POINTER_MODE`, or `SCROLL_MODE` transitions immediately to `PAUSED`, pending commands are canceled, and no input is sent to the new foreground application. `IDLE` stays `IDLE`; `PAUSED` stays `PAUSED`; `ERROR` stays `ERROR`. Resume requires a thumbs-up after the target is foreground and revalidated.

Shutdown behavior: the exit hotkey (`Ctrl+Alt+Q` by default) or a sustained shaka moves any non-terminated state to `EXITING`; the runtime stops accepting commands, cancels pending commands, stops capture, joins workers with bounded timeouts, releases the camera and Win32 resources, and terminates. The status overlay closes last.

**Alternatives considered:** Automatic activation is lower-friction but unsafe; a separate activation gesture would expand the vocabulary; allowing direct pointer/scroll switching adds ambiguous gestures and conflicts.

### D4. Four-thread runtime with a single-slot frame mailbox and one command worker

- **Capture thread:** reads camera frames, timestamps them, and overwrites a single-slot mailbox. It never waits for inference.
- **Vision worker:** takes the newest frame, preprocesses, runs tracking/landmark extraction, computes features, classifies gestures, performs temporal validation, and pushes semantic events.
- **Main/state thread:** runs the state machine, validates commands, polls keyboard shortcuts, owns the click arbiter, publishes status feedback, and enqueues commands. It never calls a potentially blocking Win32 adapter API directly.
- **Command worker:** executes adapter calls one at a time in FIFO order, refreshes the target snapshot cache, and reports acknowledgements, structured errors, and timeouts.

The command worker is selected instead of synchronous adapter execution so a slow or unresponsive adapter call cannot freeze the state thread or the keyboard exit path. Ordering and shutdown are specified in D12.

**Alternatives considered:** Synchronous adapter execution on the state thread is simpler but can block pause/exit handling; a thread per stage adds synchronization and queue latency; multiprocessing adds startup, IPC, and packaging cost; asyncio does not help native CV work or Win32 calls.

### D5. PowerPoint target model and win32/ctypes adapter, fail closed

The adapter discovers `POWERPNT.EXE`, enumerates top-level windows owned by that process, and classifies the presentation target into one of four kinds:

| Target kind | Navigation | Pointer/click/scroll | Notes |
|---|---|---|---|
| `NORMAL_SLIDESHOW` | supported | supported | Full-screen slideshow window foreground on a monitor |
| `PRESENTER_VIEW` | supported | rejected | Presenter console foreground; slideshow output on another monitor |
| `EDIT_MODE` | rejected | rejected | PowerPoint editor, no slideshow output |
| `UNKNOWN` | rejected | rejected | Ambiguous ownership, window shape, or monitor mapping |

Target identification uses process ownership, foreground status, visibility, window class/title signals, full-screen bounds against a monitor, and presenter-console/output pairing. A target snapshot records process ID, window handle(s), monitor rectangle, target kind, capabilities, presentation title if available, and capture time. The snapshot is refreshed by the command worker at least every 250 ms; a snapshot older than 1,000 ms is treated as unknown, reported as `TARGET_UNAVAILABLE`, and the state layer enters `PAUSED` without dispatching anything.

Normal slideshow: the slideshow window must be foreground and cover one monitor. Extended displays are supported by mapping pointer coordinates to the slideshow monitor, not the primary monitor. Multiple monitors are supported only when exactly one candidate slideshow/output window can be identified; otherwise the target is `UNKNOWN` and no input is sent.

Presenter View: navigation is supported when the foreground window belongs to PowerPoint and is either the presenter console or the slideshow output of the same presentation. Pointer, click, and scroll are rejected with `UNSUPPORTED_PRESENTER_VIEW` because synthesizing them would either target the wrong monitor or steal focus from the presenter console. The state layer prevents entering pointer/scroll modes when the target reports those capabilities as unavailable.

Edit mode: activation is rejected and no input is sent. Unknown configuration: fail closed, report diagnostics listing candidate process/window/class/monitor data, and send nothing.

Every input is preceded by an immediate revalidation of process ID, window handle, target kind, foreground status, and monitor bounds. If anything changed, the adapter returns `TARGET_CHANGED` or `FOCUS_LOST` and sends no input. The adapter uses `ctypes` and Win32 APIs only; no COM dependency in v1.

**Alternatives considered:** PowerPoint COM automation gives richer state but adds a dependency, can block, and is not uniformly available. COM can be added behind the same adapter interface later if window heuristics fail validation. UI Automation has similar cost and fragility.

### D6. Stdlib configuration, logging, and telemetry

Configuration is a JSON file in `%APPDATA%\AirCue\config.json`, merged over code defaults. The parser validates types and ranges and rejects unknown keys with a diagnostic. Logs are JSON lines in `%LOCALAPPDATA%\AirCue\logs` with rotation. Performance reports are JSON. No metrics SDK, TOML writer, or logging framework is added.

**Alternatives considered:** TOML is friendlier but requires a writer dependency; YAML adds parsing and security surface; a settings UI is out of scope for v1.

### D7. Performance measurement model

The system records distinct metrics, not a single "end-to-end" number:

| Metric | Start | End |
|---|---|---|
| Stage latency | stage entry | stage exit |
| Recognition compute | preprocessed frame available | gesture classification complete (excludes temporal confirmation) |
| Pipeline latency | frame capture | validated command enqueued or state action committed |
| Command dispatch latency | command enqueued | adapter acknowledgement |
| Gesture response latency | first frame matching the gesture onset predicate | action completion |
| Capture-to-action latency | frame capture | action completion |

Gesture response includes temporal confirmation, click arbitration, and every other intentional recognition delay. Action completion means adapter acknowledgement for presentation commands, the accepted state transition for state-only actions such as pause, resume, activation, and mode changes, and entering `EXITING` for exit. The gesture recognizer attaches an onset timestamp and onset frame sequence to each candidate; without that marker, gesture response cannot be measured honestly.

The original proposed 100 ms p50 / 150 ms p95 baseline targets are retained only as a **base budget** for actions with no intentional delay, such as continuous pointer movement and scrolling. For discrete gestures, the proposed target is the base budget plus the configured confirmation window and intentional arbitration/hold delay:

- Baseline base budget: p50 < 100 ms, p95 < 150 ms.
- Mid/high-end base budget: p50 < 70 ms, p95 < 100 ms.
- Static gesture target: base budget + configured confirmation window.
- Single click target: base budget + 100 ms pinch-release confirmation + 350 ms pending-click window.
- Exit target: base budget + 1,500 ms hold window.
- Double-click is reported separately; no fixed target is claimed until calibration.

The original 50 ms baseline / 35 ms mid/high-end recognition processing targets remain proposed **per-frame compute** targets, excluding temporal confirmation. They are not gesture-response targets.

Replay benchmarks use a deterministic frame fixture and measure compute, pipeline, and dispatch with a fake or recorded adapter; they cannot provide camera-to-action evidence. Live-camera benchmarks use a real camera and record real onset-to-action timing; camera-to-action acceptance requires a real adapter or an observed screen action, not a replay. Reports carry a `benchmark_mode` (`REPLAY` or `LIVE_CAMERA`) and an `adapter_mode` (`REAL` or `NOOP`) label, and results from different modes are never combined.

Instrumentation overhead: the 2 ms target is proposed, not verified. Measure it by alternating instrumentation-enabled and instrumentation-disabled blocks on the same replay fixture, using an external timer around the processing loop; run warm-up plus at least five 60-second blocks per condition, and report the median and p95 delta with a confidence interval. A live smoke test verifies that enabling instrumentation does not cause dropped frames.

**Alternatives considered:** External profilers are useful for development but cannot produce product acceptance reports; unbounded sample lists would violate the memory ceiling; a single aggregate latency hides confirmation delay and adapter time.

### D8. Hardware tiers are hints; calibration selects the profile and backend

Tier 1, Tier 2, and Tier 3 are initial profile hints derived from CPU identity, core count, RAM, and detected GPU adapters. They are not performance classifications. A short startup calibration measures inference throughput and latency, then downgrades the profile when measured performance misses the target; upward adjustment requires sustained evidence. Hardware names alone never determine acceptance.

The benchmark gate compares CPU and any supported GPU backend on representative inference work. CPU is selected unless a GPU backend is at least 10% lower in median latency, no worse in p95, and no worse in reliability across the measurement window. If results are within the margin, confidence intervals overlap, or GPU reliability is worse, CPU wins. Integrated GPUs are evaluated on the same basis as discrete GPUs; no discrete-GPU advantage is assumed.

GPU acceleration remains optional. The core installation is CPU-only; a GPU dependency is added only after a supported Windows backend passes the gate and the dependency is justified by measured benefit. If no supported GPU path exists, the outcome is a documented CPU-only decision, not a failed milestone.

**Alternatives considered:** Hard-coding CPU model lists becomes stale and misses thermal throttling; promising GPU acceleration without a supported Windows path would be misleading.

### D9. Pointer pose, pinch geometry, and click arbitration

**Pointer pose:** index finger extended, thumb extended, thumb-tip to index-tip separation greater than 0.40 palm units, middle/ring/pinky curled, and all required landmarks valid above the confidence threshold. The pointer source is the index fingertip. A pointer pose with insufficient separation is not a valid pointer pose; it cannot move the cursor or trigger a mode change.

**Pinch cycle:** initiation when thumb-tip to index-tip distance is below 0.22 palm units for 100 ms; release when distance is above 0.32 for 100 ms; neutral re-arm when distance is above 0.40 for 300 ms. The hysteresis band prevents jitter from producing repeated clicks. A pinch is only valid when the required landmarks are present and confident; partial occlusion freezes the pointer and cannot produce a click or mode change.

**Mode entry:** a pinch confirmed in `ACTIVE` enters `POINTER_MODE` and is consumed. It cannot also produce a click. The user must release and re-arm before the first click.

**Long pinch:** a closed pinch held for 700 ms in `POINTER_MODE` emits `EXIT_POINTER_MODE` immediately, cancels any pending click, and suppresses the click that would otherwise occur on release.

**Click arbitration:** a valid pinch release before the long-pinch threshold creates a `CLICK_CANDIDATE`. The click arbiter holds it for 350 ms:

- If a second candidate arrives within the window, it dispatches one double-click immediately and cancels the pending single click.
- If the window expires, it dispatches one single click.
- Pointer movement is frozen during the pending window so the click lands where the user released the pinch.
- Tracking loss, focus loss, pointer invalidity, pause, mode change, error, or long pinch cancels the pending click without dispatching anything.
- A click is never generated by pointer movement, mode entry, partial occlusion, or a continuous pinch.

This adds up to 350 ms of arbitration latency to every single click, on top of the 100 ms pinch-release confirmation. That delay is the deliberate cost of unambiguous double-click recognition; it is documented in `pointer-and-scroll` and reported as an intentional delay in performance results.

### D10. Initial thresholds (configuration defaults, not acceptance claims)

| Behavior | Initial default |
|---|---|
| Activation | thumbs-up held 800 ms in `IDLE`, or `Ctrl+Alt+A` |
| Resume | thumbs-up held 250 ms in `PAUSED` |
| Deactivation / exit | `Ctrl+Alt+D` to `IDLE`; `Ctrl+Alt+Q` to exit |
| Static confirmation | fist 200 ms; peace 250 ms; shaka 1,500 ms |
| Per-gesture cooldown | 500 ms |
| Re-arm | neutral or different pose for 300 ms |
| Rotation activation | 25 degrees from neutral; neutral band +/- 8 degrees |
| Continuous rotation | disabled by default; 30-degree repeat step, 400 ms minimum interval, max 2 events/s |
| Pinch initiation / release / re-arm | below 0.22 / above 0.32 / above 0.40 palm units for 100 ms / 100 ms / 300 ms |
| Long pinch | 700 ms in `POINTER_MODE` |
| Double-click window | 350 ms |
| Pointer dead zone | 0.01 normalized units |
| Pointer smoothing | adaptive EMA, alpha 0.20-0.45, max added latency 40 ms |
| Scroll dead zone | 0.05 normalized units; max 10 wheel notches/s |
| Tracking loss | freeze output immediately; no command from the gap after 300 ms; `IDLE` after 1,000 ms |
| Primary hand switch | 500 ms invalid or absent before switching to another hand |
| Camera freeze | no frame for 2,000 ms |
| Camera reconnect | 3 attempts, 500 ms backoff |
| Target snapshot freshness | refresh 250 ms; stale after 1,000 ms |
| Command TTL | pointer 100 ms; scroll 150 ms; click 250 ms; navigation 500 ms |
| Adapter call deadline | 150 ms; unresponsive after 2x deadline |
| Performance window | 10 s rolling; benchmark 10 s warm-up + 60 s measurement |
| Instrumentation overhead run | 5 x 60 s per condition plus warm-up |

All values live in validated config. Calibration changes defaults only with user-test evidence.

### D11. Architecture and module layout

```
src/aircue/
  capture/        camera device, frame source, single-slot mailbox
  vision/         preprocessing, hand tracker, landmark features
  gestures/       vocabulary, geometry, temporal validator, recognizer, click candidates
  state/          states, authoritative transitions, activation, feedback port
  commands/       command manager, click arbiter, gating, priority
  dispatch/       bounded FIFO command worker, envelopes, TTLs, cancellation
  presentation/   adapter protocol, PowerPoint target model, Win32 adapter, input synthesis
  performance/    timings, metrics ring, replay/live benchmarks, reports
  hardware/       tier hints, profiles, calibration, backend selection
  config/         schema, defaults, JSON loading, validation
  diagnostics/    logging, fault records, privacy controls
  ui/             non-activating status overlay
  app/            composition root, runtime loop, CLI, keyboard shortcuts
tests/
  unit/           synthetic landmarks, geometry, state table, gating, arbitration
  integration/    pipeline with fake source/adapter, fault injection
  contract/       adapter and config contracts
  fixtures/       synthetic landmarks; consented/short video fixture
  performance/    replay and live benchmark scripts, not CI gates
  manual/         real-world protocol, hardware matrix, PowerPoint mode matrix
```

Dependency rule: `gestures/`, `state/`, and `commands/` import only domain types; `presentation/` implements the adapter protocol; `app/` is the only composition root. The vision layer never imports PowerPoint code.

### D12. Command dispatch, error, and concurrency model

- No queue grows without a bound. The frame mailbox keeps one slot; the semantic event queue is bounded and observable; the command queue is bounded at eight entries.
- The command worker executes one envelope at a time in FIFO order. Envelopes carry a monotonic sequence number, state generation, target snapshot, enqueue time, expiry time, and command payload.
- Adjacent `POINTER_MOVE` envelopes may be coalesced in the queue, with the newest position winning, but a pointer move is never reordered across a click, navigation, or scroll command.
- Every command has a TTL. An envelope older than its TTL is rejected as `STALE_COMMAND`, is never executed, and is counted without changing state or requiring resume. Non-idempotent commands (navigation, click, double-click) are never retried.
- Every state transition increments the state generation. Pending envelopes from an older generation are canceled before dispatch. The click arbiter is cleared on the same events.
- Adapter calls have a 150 ms deadline. If the worker has not acknowledged within twice the deadline, the adapter is marked unresponsive, dispatch stops, and the state enters `ERROR`. If the call returns after the deadline, it is reported as `TIMEOUT` and its effect is not retried.
- Recoverable failures (`FOCUS_LOST`, `TARGET_CHANGED`, `TARGET_UNAVAILABLE`, `UNSUPPORTED_PRESENTER_VIEW`) transition to `PAUSED` and require deliberate resume. `STALE_COMMAND` is dropped and counted without a state transition. Unrecoverable failures (`INPUT_BLOCKED`, `ADAPTER_UNAVAILABLE`, `TIMEOUT`, `INTERNAL`) transition to `ERROR`.
- The target snapshot cache is refreshed by the command worker. The state thread reads it without blocking; a stale snapshot is reported as `TARGET_UNAVAILABLE`, which maps to `PAUSED`.
- The command worker is a daemon thread so a wedged Win32 call cannot prevent process exit. Normal shutdown stops acceptance, cancels pending work, sends a sentinel, and joins for one second. If the join times out, the abandonment is logged as a forced shutdown; no child process is created.
- The keyboard shortcuts are polled with `GetAsyncKeyState` on the state thread so they work while PowerPoint is foreground.

### D13. Testing and release strategy

- Unit tests use synthetic landmarks and a fake clock; they never require a camera or PowerPoint.
- Integration tests inject a fake frame source and a fake adapter; contract tests verify the real adapter's target classification, revalidation, and input guards with mocked Win32 calls.
- The authoritative transition table is tested exhaustively, including every rejected transition.
- Click arbitration tests cover pending single click, immediate double-click, long-pinch priority, mode-entry consumption, cancellation, and hysteresis.
- Performance tests run outside CI on named hardware; CI runs unit/integration tests on `windows-latest` with lint and type checks.
- Replay benchmarks and live-camera benchmarks are separate reports and are never compared as if they measured the same thing.
- Reliability tests include a 60-minute soak, fault injection (camera loss, NaN frames, low confidence, focus loss, adapter failure, unresponsive adapter), and resource-leak checks.
- Real-world validation uses at least five presenters across three environments and three lighting conditions; results are recorded as measured evidence, not inferred from unit tests.
- GitHub readiness includes `README`, `CONTRIBUTING`, `SECURITY`, `.gitignore`, `pyproject.toml`, CI workflow, and a hardware/performance results template. `LICENSE` is added only after the owner confirms a license choice.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Delayed single-click dispatch adds up to 350 ms and may feel unresponsive. | Document the trade-off, freeze the pointer during the window, and report click latency separately. Revisit the window only with user-test evidence. |
| The p50 < 100 ms base target is aggressive for Python + a pretrained tracker on Celeron hardware. | Measure in Phase 2. Use 30 FPS capture with 10-15 FPS processing and a single-slot mailbox to bound queue wait. Apply the base target only to actions without intentional delay; re-baseline with evidence if needed. |
| Static gestures cannot meet a 100 ms target once 200-350 ms confirmation is included. | Use the confirmation-aware target formula in D7 and report intentional delay explicitly; never claim the base target for a static gesture. |
| MediaPipe Windows packaging or CPU latency may not meet the budget. | Phase 2 spike with the real model and target hardware; fall back to ONNX Runtime with a compatible model; keep the tracker behind an interface. |
| GPU acceleration may not be available through the Python runtime on Windows. | Treat GPU as optional; run the conditional spike only after a supported backend is identified; default to CPU; record a CPU-only decision as a valid outcome. |
| PowerPoint slideshow window detection is version-fragile, especially with Presenter View and extended displays. | Conservative multi-signal target model, snapshot revalidation before every input, fail closed on ambiguity, diagnostics for candidate windows, and a documented Presenter View pointer limitation. |
| A command worker can hang if a Win32 call blocks. | Daemon worker, per-call deadline, heartbeat/unresponsive detection, bounded shutdown join, and forced-shutdown logging. |
| False-positive gestures or poor ergonomics. | Deliberate activation, temporal confirmation, cooldowns, neutral re-arm, confidence gates, and real-user calibration. |
| Python GIL or thread contention introduces latency. | Native inference dominates; keep the hot path out of Python object churn; profile queue wait and dispatch; multiprocessing is a contingency if profiling proves it necessary. |
| Test fixtures with real hands create privacy/licensing issues. | Use synthetic landmarks for unit tests and a short, consented, license-clean clip for inference benchmarks; never record by default. |
| Hardware diversity exceeds the test matrix. | Publish minimum/recommended/enhanced requirements, ship hint-based profiles, and state that support is validated only on tested machines. |
| License ambiguity blocks publication. | Keep license selection as an explicit owner decision; do not create a license file or claim a license in the README without written confirmation. |

## Migration Plan

This is a greenfield implementation, so there is no data or user migration. The rollout order follows the architecture dependency chain:

1. Repository foundation, packaging, CI, configuration, and OpenSpec preservation.
2. Vision pipeline: camera, tracker, features, validity, latency spike.
3. Gesture recognition: geometry, temporal validation, pinch/pointer pose, events, priorities.
4. State machine: authoritative transitions, deliberate activation, command gating, feedback port.
5. Presentation adapter: target identification, capability matrix, input synthesis, bounded command worker.
6. Pointer and scroll behavior: mapping, smoothing, click arbitration, scroll.
7. Runtime integration: composition root, four threads, keyboard shortcuts, status overlay, logs.
8. Performance and hardware adaptation: metrics, replay/live benchmarks, instrumentation overhead, profiles, conditional GPU gate.
9. Reliability and real-world validation: fault injection, soak, privacy, presenters, hardware matrix.
10. Release readiness: full verification, owner license decision, GitHub settings, acceptance report.

Each phase is independently revertible by commit. No phase may claim a performance or reliability target without a recorded measurement. If a phase fails a gate, the next phase does not proceed until the failure is documented and the target or approach is re-approved.

## Open Questions

- **License:** the owner must choose a license. No license file is created, and no license is claimed in the README, until that decision is recorded.
- **Supported PowerPoint versions:** v1 targets PowerPoint 2019/2021/365 on Windows 10/11, 64-bit, and validates target identification against those. Confirm whether older versions or 32-bit Office must be supported.
- **Presenter View scope:** v1 supports Presenter View navigation only and rejects pointer/click/scroll there. Confirm that this limitation is acceptable for the release.
- **Hardware access:** which Tier 1, Tier 2, and Tier 3 machines, and how many real presenters, are available for the validation plan?
- **GPU spike:** is a supported Windows GPU path available (MediaPipe GPU delegate or ONNX Runtime DirectML) that can be benchmarked without shipping the dependency first?
- **Fixture availability:** can the project include a short, consented hand-gesture video for deterministic inference benchmarks, or must replay mode rely on synthetic landmarks only?

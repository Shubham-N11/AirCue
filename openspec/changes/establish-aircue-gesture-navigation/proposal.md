# Proposal

## Why

Solo presenters must divide attention between explaining content, changing slides, operating a pointer, and managing their laptop. AirCue removes that distraction by turning a standard laptop webcam into a hands-free presentation controller, with reliability and latency treated as product requirements rather than afterthoughts.

This change establishes the complete product, architecture, performance, and reliability contract for AirCue. The repository is greenfield: it contains no application source, tests, or benchmark data, so the historical claim of 277 passing tests cannot be verified and nothing is treated as already implemented.

## What Changes

- Introduce a Windows desktop application written in Python that processes webcam frames through capture, hand tracking, landmark extraction, gesture recognition, temporal validation, deliberate activation, state/command gating, command dispatch, and a PowerPoint adapter.
- Define a nine-gesture vocabulary covering slide navigation, pause/resume, deliberate activation, pointer mode, clicking, scrolling, and intentional exit, including debounce, cooldown, and temporal-confirmation rules.
- Define an eight-state interaction model (`INITIALIZING`, `IDLE`, `ACTIVE`, `PAUSED`, `POINTER_MODE`, `SCROLL_MODE`, `EXITING`, `ERROR`) with a single authoritative transition table, deliberate activation (thumbs-up hold or keyboard shortcut), visible non-activating status feedback, explicit tracking-loss/focus-loss behavior, safe recovery, and shutdown rules.
- Define PowerPoint target identification and validation for normal slideshow, Presenter View, extended displays, multiple monitors, edit mode, foreground changes, and unknown window configurations. The adapter fails closed whenever the intended target is not confidently identified; pointer, click, and scroll are supported only in a normal full-screen slideshow in v1.
- Define click arbitration: a pending single click dispatched after the 350 ms double-click window, immediate double-click when a second pinch arrives, long-pinch priority over clicking, cancellation on loss of tracking/focus, pinch hysteresis, and neutral re-arming. The resulting single-click delay is an explicit responsiveness trade-off.
- Define a bounded command dispatcher with FIFO ordering, per-command deadlines, stale-command rejection, cancellation on state changes, structured errors, and a documented shutdown path.
- Define hardware tiers as initial profile hints, not definitive classifications; benchmark CPU and any supported GPU backend; prefer CPU when results are close or GPU reliability is worse; keep GPU acceleration optional and evidence-gated.
- Separate per-stage inference latency, pipeline latency, command dispatch latency, and gesture-onset-to-visible-action latency. Keep replay benchmarks separate from live-camera benchmarks and prohibit replay results from being used as camera-to-action evidence.
- Define degraded-condition handling and safe recovery for hand loss, occlusion, multiple hands, poor lighting, camera failure, invalid landmarks, focus loss, adapter failure, and unresponsive adapter calls.
- Define a validation strategy spanning unit, integration, performance, reliability, hardware, and real-presentation testing.
- Establish GitHub-ready project scaffolding, packaging, CI, and documentation. License selection is an explicit owner decision; no license file is created or published without confirmation.

**Non-goals:** macOS/Linux support, cloud inference, presentation software other than Microsoft PowerPoint, custom model training, dedicated depth/RGB hardware, universal hardware compatibility, FPS-first optimization, automatic activation from hand presence alone, and pointer/click/scroll control in Presenter View.

## Capabilities

### New Capabilities

- `vision-pipeline`: camera capture, bounded frame handling, hand detection/tracking, landmark validity, and feature extraction.
- `gesture-recognition`: gesture vocabulary, static/dynamic classification, pinch and pointer-pose geometry, temporal confirmation, debounce/cooldown, activation/resume events, and conflict resolution.
- `pointer-and-scroll`: pointer coordinate mapping to the slideshow display, cursor stabilization, click arbitration, pinch hysteresis, and scroll-mode behavior.
- `interaction-state`: authoritative operating states and transitions, deliberate activation, mode exclusivity, command gating, visible feedback, tracking/focus loss, recovery, and shutdown.
- `presentation-control`: PowerPoint target identification and compatibility handling, focus/slideshow validation, bounded command dispatch, input isolation, and failure reporting.
- `hardware-adaptation`: hardware hints, calibrated profiles, adaptive inference frequency, and benchmark-driven CPU/GPU backend selection.
- `performance-observability`: stage, pipeline, dispatch, and gesture-response metrics; replay and live-camera benchmark separation; resource metrics; instrumentation-overhead methodology.
- `reliability-safety`: degraded input handling, tracking loss, camera/adapter faults, focus safety, safe exit, resource cleanup, and crash-free operation.

### Modified Capabilities

None. No capabilities currently exist under `openspec/specs/`.

## Impact

- **New code:** Python application package, vision/gesture/state/command domain modules, bounded command dispatcher, Windows presentation adapter, status overlay, benchmark and diagnostic tooling, and test suites.
- **Runtime:** Windows 10/11, a standard webcam, Python 3.11+, PowerPoint for presentation actions, and a non-activating status overlay for visible state feedback. Hand-tracking and vision dependencies are selected in design and must pass Windows compatibility and benchmark gates.
- **External interfaces:** PowerPoint via Windows APIs and simulated input; no cloud services. Presenter View supports navigation only in v1; pointer/click/scroll are rejected.
- **Operations:** local-only processing, structured logs, and opt-in performance reports containing no camera imagery by default.
- **Repository:** currently uninitialized beyond OpenSpec; implementation will add source, tests, CI, packaging, and contributor documentation. License selection remains an owner decision.
- **Risk:** all performance and reliability targets are unverified proposals until measured on representative hardware. The 2 ms instrumentation-overhead target is proposed, not proven.

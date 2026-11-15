# Spec Delta

## Purpose

Measure per-stage, pipeline, dispatch, and gesture-response latency separately, keep replay and live-camera benchmarks distinct, and report resource use so performance claims are evidence-based rather than inferred.

## ADDED Requirements

### Requirement: Stage timing

The system SHALL record monotonic start and completion timestamps for camera capture, frame-queue wait, preprocessing, inference, landmark processing, feature extraction, gesture classification, temporal confirmation, command validation, dispatch queue wait, and adapter execution.

#### Scenario: Stage timings recorded

- **WHEN** a command completes
- **THEN** timings for every stage in its path are recorded

### Requirement: Pipeline latency

Pipeline latency SHALL be measured from the frame capture timestamp to the validated command being enqueued or, for a state-only action, the accepted state transition, including preprocessing, inference, feature extraction, gesture classification, temporal confirmation, and state validation.

#### Scenario: Pipeline latency recorded

- **WHEN** a validated command is enqueued
- **THEN** its capture-to-enqueue duration is recorded

#### Scenario: State action pipeline recorded

- **WHEN** a state-only action such as pause is accepted
- **THEN** its capture-to-transition duration is recorded as pipeline latency

### Requirement: Command dispatch latency

Command dispatch latency SHALL be measured from command enqueue to adapter acknowledgement, including dispatch queue wait, target revalidation, and adapter execution.

#### Scenario: Dispatch latency recorded

- **WHEN** the adapter acknowledges a command
- **THEN** its enqueue-to-acknowledgement duration is recorded

### Requirement: Gesture response latency

Gesture response latency SHALL be measured from the first frame matching the gesture onset predicate to action completion. Action completion is adapter acknowledgement for presentation commands, the accepted state transition for state-only actions, and entering EXITING for exit. It SHALL include temporal confirmation, click arbitration, and every other intentional recognition or hold delay.

#### Scenario: Static gesture response

- **WHEN** a fist is confirmed and its pause transition is accepted
- **THEN** the duration from the first fist-onset frame to the accepted PAUSED transition is recorded as gesture response latency

#### Scenario: Click response

- **WHEN** a single click is dispatched after the pending window
- **THEN** its gesture response latency includes the 100 ms release confirmation and the 350 ms pending-click window

#### Scenario: Exit response

- **WHEN** a shaka exit is accepted
- **THEN** its gesture response latency includes the 1,500 ms hold window and ends when EXITING is entered

### Requirement: Capture-to-action latency

Capture-to-action latency SHALL be measured from the frame capture timestamp to action completion and SHALL be reported separately from gesture response latency.

#### Scenario: Capture-to-action recorded

- **WHEN** an action completes
- **THEN** both capture-to-action and gesture-response durations are available

### Requirement: Onset metadata

Every gesture candidate SHALL carry the first onset frame sequence and monotonic timestamp. Performance reporting SHALL use that metadata rather than the confirmation frame.

#### Scenario: Onset used for measurement

- **WHEN** a candidate is confirmed several frames after onset
- **THEN** its response measurement starts at the recorded onset, not at confirmation

### Requirement: Percentile reporting

The system SHALL report p50 and p95 for every measured latency, together with sample count, benchmark mode, adapter mode, target basis, and intentional delay for the action class. The operational performance window SHALL be a 10-second rolling window; benchmark measurement SHALL use a 10-second warm-up followed by 60 seconds of measurement.

#### Scenario: Percentile report

- **WHEN** the measurement window closes
- **THEN** the report includes p50, p95, sample count, benchmark mode, adapter mode, target basis, and intentional delay

### Requirement: Base latency targets

Actions with no intentional recognition delay SHALL be compared against proposed base targets: baseline p50 under 100 ms and p95 under 150 ms; mid/high-end p50 under 70 ms and p95 under 100 ms. These values are proposed targets, not verified results.

#### Scenario: Pointer movement meets base target

- **WHEN** pointer movement p50 and p95 are within the active profile's base targets
- **THEN** the report marks the base target as passed

#### Scenario: Base target missed

- **WHEN** pointer movement p95 exceeds the base target
- **THEN** the report marks the base target as failed and identifies the slowest stage

### Requirement: Gesture response target formula

Discrete gesture targets SHALL be the base target plus the configured confirmation window and intentional arbitration or hold delay. Single click adds the 100 ms release confirmation and the 350 ms pending window; exit adds the 1,500 ms hold window. Double-click SHALL be reported without a fixed target until calibration.

#### Scenario: Static gesture target

- **WHEN** a fist has a 200 ms confirmation window and a 100 ms base target
- **THEN** its proposed baseline p50 target is 300 ms

#### Scenario: Single-click target

- **WHEN** a single click has a 100 ms release confirmation, a 350 ms pending window, and a 100 ms base target
- **THEN** its proposed baseline p50 target is 550 ms

#### Scenario: Double-click reporting

- **WHEN** a double-click response is measured
- **THEN** it is reported separately without claiming a fixed target

### Requirement: Recognition compute budget

Recognition compute SHALL be measured from preprocessed frame availability to the end of gesture classification, excluding temporal confirmation and dispatch. It SHALL be compared against proposed per-frame targets of 50 ms baseline and 35 ms mid/high-end.

#### Scenario: Recognition compute within budget

- **WHEN** recognition compute p95 is at or below the active profile target
- **THEN** the report marks the recognition compute target as passed

#### Scenario: Confirmation excluded from compute

- **WHEN** a gesture has a 250 ms confirmation window
- **THEN** the confirmation time is excluded from recognition compute but included in gesture response latency

### Requirement: Replay benchmark

Replay benchmarks SHALL use a deterministic frame fixture and MAY use a simulated clock. They SHALL measure compute, pipeline, and dispatch behavior and SHALL NOT be used as evidence of live camera-to-action or live gesture-response performance.

#### Scenario: Replay report

- **WHEN** a replay benchmark completes
- **THEN** its report is labeled REPLAY and identifies the fixture hash and simulated-clock use

#### Scenario: Replay cannot prove camera latency

- **WHEN** only replay results exist
- **THEN** no camera-to-action or live gesture-response target is considered passed

### Requirement: Live-camera benchmark

Live-camera benchmarks SHALL use a real camera and measure camera-to-onset and gesture-response timing. Reports SHALL label the adapter as REAL or NOOP. Camera-to-action acceptance SHALL require a real adapter or an observed screen action.

#### Scenario: Live-camera report

- **WHEN** a live-camera benchmark completes
- **THEN** its report is labeled LIVE_CAMERA and includes camera configuration and adapter mode

#### Scenario: No-op adapter limitation

- **WHEN** a live-camera benchmark uses a NOOP adapter
- **THEN** the report does not claim visible-action or camera-to-action acceptance

### Requirement: Benchmark mode separation

Replay and live-camera results SHALL NOT be combined, averaged, or compared as if they measured the same conditions. Every report SHALL carry a benchmark mode and fixture or camera identity.

#### Scenario: Mixed results rejected

- **WHEN** a report combines REPLAY and LIVE_CAMERA samples
- **THEN** the report is invalid and cannot be used for acceptance

### Requirement: Instrumentation overhead measurement

The 2 ms instrumentation-overhead limit SHALL be treated as a proposed target, not a verified result. Overhead SHALL be measured by alternating instrumentation-enabled and instrumentation-disabled blocks on the same replay fixture, using an external timer around the processing loop, with warm-up and at least five 60-second blocks per condition.

#### Scenario: Overhead measured

- **WHEN** the overhead protocol completes
- **THEN** the report provides median and p95 enabled-minus-disabled deltas with a confidence interval

#### Scenario: Overhead target missed

- **WHEN** the measured delta exceeds 2 ms
- **THEN** the report marks the proposed overhead target as failed

#### Scenario: Instrumentation disabled

- **WHEN** instrumentation is disabled
- **THEN** processing continues and the external timer still measures the loop

### Requirement: Resource metrics

The system SHALL record process CPU utilization, memory usage, processed frame rate, capture frame rate, dropped-frame count, and queue depth during operation.

#### Scenario: Resource report

- **WHEN** performance reporting is enabled
- **THEN** the report contains CPU, memory, frame-rate, drop, and queue-depth metrics

### Requirement: FPS not an acceptance metric

Frames-per-second SHALL be reported for diagnosis but SHALL NOT be used as the primary acceptance metric; latency percentiles and command reliability SHALL determine performance acceptance.

#### Scenario: High FPS with poor latency

- **WHEN** the pipeline reports high FPS but gesture response p95 exceeds its target
- **THEN** the performance result is marked failed

### Requirement: Privacy of telemetry

Performance reports SHALL NOT contain camera frames or images by default, and any debug image capture SHALL require explicit opt-in.

#### Scenario: Default report

- **WHEN** a performance report is generated without debug opt-in
- **THEN** it contains timing and resource metrics only, with no image data

### Requirement: Log correlation

Performance, state, gesture, and dispatch records SHALL share a session identifier, state generation, and monotonic timestamps so a command can be traced across stages.

#### Scenario: Trace a command

- **WHEN** a command is traced through the logs
- **THEN** all related stage, state, gesture, and dispatch records share one session identifier, generation, and ordered timestamps

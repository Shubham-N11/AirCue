# Spec Delta

## Purpose

Use hardware specifications only as initial profile hints, then select resolution, inference frequency, and execution backend from measured behavior so the same application runs acceptably across laptop tiers without assuming GPU superiority.

## ADDED Requirements

### Requirement: Hardware specifications are hints

The application SHALL derive an initial Tier 1, Tier 2, or Tier 3 hint from CPU identity, core count, RAM, and detected GPU adapters, and SHALL expose the hint and its evidence in diagnostics. The hint SHALL NOT be treated as a definitive performance classification.

#### Scenario: Baseline hint

- **WHEN** the host matches the Tier 1 hint criteria
- **THEN** the application starts with the Tier 1 profile and marks it as an uncalibrated hint

#### Scenario: High-end hint

- **WHEN** the host matches the Tier 3 hint criteria
- **THEN** the application starts with the Tier 3 profile and marks it as an uncalibrated hint

### Requirement: Calibration overrides hints

A startup calibration SHALL measure inference throughput and latency and SHALL downgrade the profile when measured performance misses the profile target. Upward adjustment SHALL require sustained evidence, not a hardware name.

#### Scenario: Strong specification, weak result

- **WHEN** a Tier 3 hint measures latency above the Tier 3 target
- **THEN** the application selects a lower profile and records the measured reason

#### Scenario: Modest specification, strong result

- **WHEN** a Tier 1 hint sustains latency within the Tier 2 target
- **THEN** the application may select Tier 2 only after the sustained measurement window passes

### Requirement: Baseline profile

Tier 1 SHALL default to 640x360 capture, 10-15 processed frames per second, CPU inference, and resource-conserving tracking.

#### Scenario: Tier 1 operation

- **WHEN** the calibrated Tier 1 profile is active
- **THEN** capture uses 640x360 and processing stays within the configured 10-15 FPS range unless adaptation lowers it

### Requirement: Mid-range profile

Tier 2 SHALL default to 720p capture and 20-30 processed frames per second where measured latency remains within target.

#### Scenario: Tier 2 operation

- **WHEN** the calibrated Tier 2 profile is active and measured latency is within target
- **THEN** capture uses 720p and processing stays within 20-30 FPS

### Requirement: High-end profile

Tier 3 SHALL permit higher tracking frequency and, only when the benchmark gate selects it, GPU acceleration.

#### Scenario: Tier 3 operation

- **WHEN** the calibrated Tier 3 profile is active and a GPU backend passes the benchmark gate
- **THEN** the GPU backend is selected and the higher tracking profile is enabled

### Requirement: Benchmark gate

On first run and after a hardware or driver change, the application SHALL benchmark CPU and every supported GPU backend on representative inference work, including warm-up, median latency, p95 latency, and failure rate. A GPU backend SHALL be selected only if it is at least 10% lower in median latency, no worse in p95, and no worse in reliability.

#### Scenario: GPU clearly faster

- **WHEN** a GPU backend is at least 10% lower in median latency, no worse in p95, and no worse in reliability
- **THEN** the GPU backend is selected

#### Scenario: GPU slower than CPU

- **WHEN** GPU inference has a higher median latency than CPU inference
- **THEN** the CPU backend is selected and the GPU remains unused

#### Scenario: Results are close

- **WHEN** CPU and GPU results are within 10% or their confidence intervals overlap
- **THEN** the CPU backend is selected

#### Scenario: Benchmark failure

- **WHEN** a backend fails to initialize or produces invalid results
- **THEN** that backend is excluded and the next qualifying backend is selected

### Requirement: No GPU technology assumption

Discrete and integrated GPUs SHALL be evaluated on the same measured criteria. The application SHALL NOT assume that a discrete GPU is faster than integrated graphics or that a GPU is faster than CPU.

#### Scenario: Discrete GPU slower

- **WHEN** a discrete GPU benchmark is slower than CPU or integrated graphics
- **THEN** it is not selected

#### Scenario: Integrated GPU competitive

- **WHEN** an integrated GPU meets the benchmark gate and the discrete GPU does not
- **THEN** the integrated GPU may be selected

### Requirement: GPU acceleration is optional

The core installation SHALL be CPU-only. A GPU dependency SHALL be added only after a supported Windows backend passes the benchmark gate and the dependency is justified by measured benefit. If no supported GPU path exists, the application SHALL operate CPU-only and record that decision.

#### Scenario: No supported GPU backend

- **WHEN** no GPU backend can be initialized on Windows
- **THEN** the application operates CPU-only without failing startup

#### Scenario: Optional GPU extra

- **WHEN** a supported GPU backend passes the gate
- **THEN** it is offered as an optional extra, not a required dependency

### Requirement: Adaptive frequency

The application SHALL adjust processed frames per second within profile bounds based on measured pipeline latency, queue depth, and CPU pressure, and SHALL increase frequency only while latency targets remain met. The intentional click window SHALL NOT be used as a reason to change frequency.

#### Scenario: Sustained overload

- **WHEN** pipeline latency exceeds the profile target for the configured window
- **THEN** processing frequency is reduced within profile bounds before commands become unreliable

#### Scenario: Recovery

- **WHEN** latency returns within target after a reduction
- **THEN** processing frequency may increase gradually up to the profile maximum

### Requirement: Backend reporting

The initial hint, calibrated profile, selected backend, processing frequency, benchmark margin, and benchmark result SHALL be recorded in diagnostics and performance reports.

#### Scenario: Startup diagnostics

- **WHEN** the application finishes startup
- **THEN** diagnostics report the initial hint, calibrated profile, backend, capture configuration, processing frequency, and benchmark evidence

### Requirement: Manual override

A user SHALL be able to force a hardware profile, execution backend, or processing frequency for troubleshooting, and the override SHALL be recorded as a non-default configuration.

#### Scenario: Forced CPU

- **WHEN** the user forces CPU execution
- **THEN** the application uses CPU regardless of benchmark result and records the override

### Requirement: Resource limits

The application SHALL reduce or suspend non-essential processing when configured CPU or memory ceilings are exceeded, while preserving pause, resume, and safe-exit behavior.

#### Scenario: Memory ceiling exceeded

- **WHEN** process memory exceeds the configured ceiling
- **THEN** non-essential diagnostics are reduced, the user is warned, and pause, resume, and exit gestures remain available

### Requirement: Architecture independence

Hardware profiles SHALL change configuration values only and SHALL NOT require a separate application build or alternate code path for each tier.

#### Scenario: Profile switch

- **WHEN** the calibrated profile changes
- **THEN** the same application binary continues running with new configuration values

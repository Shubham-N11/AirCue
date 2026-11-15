# Spec Delta

## Purpose

Acquire webcam frames and produce validated hand landmarks, per-landmark validity, and motion features for downstream gesture recognition, with bounded latency, stable hand identity, and no stale-frame backlog.

## ADDED Requirements

### Requirement: Camera capture

The system SHALL capture frames from the configured webcam using the resolution and frame rate of the active calibrated hardware profile, and SHALL report a recoverable error when the requested configuration is unavailable.

#### Scenario: Baseline capture profile

- **WHEN** the calibrated profile requests 640x360 and the webcam supports it
- **THEN** frames are captured at 640x360 at the profile's configured rate

#### Scenario: Unsupported capture configuration

- **WHEN** the webcam rejects the requested resolution or frame rate
- **THEN** the system reports a recoverable capture error and attempts the nearest supported configuration

#### Scenario: No supported configuration

- **WHEN** no requested or fallback configuration can be opened
- **THEN** the system reports a camera initialization failure and enters ERROR

### Requirement: Latest-frame processing

The vision pipeline SHALL process the most recent available frame and SHALL discard stale queued frames rather than accumulating an unbounded backlog.

#### Scenario: Inference slower than capture

- **WHEN** frames arrive faster than inference completes
- **THEN** only the newest unprocessed frame is submitted next
- **AND** older queued frames are dropped and counted

### Requirement: Independent capture and inference

Camera capture SHALL run independently of inference and gesture processing so that a slow processing stage cannot block or stall frame acquisition.

#### Scenario: Slow inference

- **WHEN** inference takes longer than the frame interval
- **THEN** capture continues and the pipeline retains at most the newest frame

### Requirement: Single primary hand tracking

The hand tracker SHALL detect and track at most one primary hand per frame, selecting the most confident valid hand when multiple hands are visible. Once selected, the primary hand SHALL remain the tracked hand while it stays valid, even if a second hand briefly reports higher confidence.

#### Scenario: One hand visible

- **WHEN** one valid hand is in view
- **THEN** the pipeline returns its landmarks and a tracking identifier

#### Scenario: Multiple hands visible

- **WHEN** two or more hands are visible
- **THEN** the pipeline tracks the most confident hand at acquisition and ignores the others

#### Scenario: No identity flapping

- **WHEN** a second hand briefly reports higher confidence than the established primary hand
- **THEN** the primary hand remains selected until it is lost or invalid for the configured switch window

#### Scenario: Primary hand lost

- **WHEN** the primary hand is lost and another valid hand is visible
- **THEN** the other hand is tracked as the new primary hand but no gesture event is emitted for the transition gap

### Requirement: Landmark validity

The pipeline SHALL reject a frame whose landmark coordinates contain non-finite or out-of-range values and SHALL mark each remaining landmark with a validity state derived from presence and confidence. It SHALL NOT pass invalid landmarks as valid to gesture recognition.

#### Scenario: Degenerate landmark frame

- **WHEN** a frame produces NaN, infinite, or out-of-range landmark coordinates
- **THEN** the frame is discarded, counted as invalid, and no gesture event is emitted

#### Scenario: Low-confidence landmark

- **WHEN** a landmark is present but below the configured confidence threshold
- **THEN** it is marked invalid and excluded from geometry that requires it

#### Scenario: Partial occlusion

- **WHEN** only some landmarks are invalid
- **THEN** the frame keeps its valid landmarks, marks the rest invalid, and gesture recognition cannot use an invalid landmark to emit a command

### Requirement: Feature extraction

The pipeline SHALL derive normalized landmark positions and motion features, including wrist rotation, pinch distance, finger extension, hand openness, and palm scale, for each valid tracked hand.

#### Scenario: Features available

- **WHEN** a valid hand is tracked with the required landmarks
- **THEN** the current features include normalized landmarks, wrist angle, pinch distance, palm scale, and per-finger extension state

#### Scenario: Missing geometry input

- **WHEN** a feature depends on a landmark marked invalid
- **THEN** that feature is reported unavailable rather than computed from a substitute value

### Requirement: Frame timestamps and sequence

Every captured frame SHALL carry a monotonic capture timestamp and a monotonically increasing frame sequence number. Every processing stage SHALL record its completion timestamp, and the capture timestamp and onset sequence SHALL be preserved through recognition so latency can be measured from gesture onset.

#### Scenario: Timestamp propagation

- **WHEN** a frame completes hand tracking and feature extraction
- **THEN** its capture timestamp, frame sequence, and stage-completion timestamps are available to recognition and performance monitoring

#### Scenario: Onset preserved

- **WHEN** a gesture candidate is later confirmed
- **THEN** the onset frame sequence and capture timestamp from the first matching frame remain available

### Requirement: Tracking presence and loss reporting

The pipeline SHALL report hand presence and absence on every processed frame, including the monotonic timestamp of the first frame in the current absence run. The state layer SHALL use that timestamp to apply the 300 ms freeze and 1,000 ms IDLE thresholds; the vision layer SHALL NOT change application state itself.

#### Scenario: Loss begins

- **WHEN** the primary hand is not detected on a processed frame
- **THEN** the pipeline reports absence with the first-absence timestamp and continues processing subsequent frames

#### Scenario: Presence returns

- **WHEN** the primary hand is detected again
- **THEN** the pipeline reports presence and the duration of the absence run

#### Scenario: No command from a gap

- **WHEN** presence returns after any absence run
- **THEN** the pipeline emits no gesture event derived from frames spanning the gap

### Requirement: Tracking continuity

The tracker SHALL preserve hand identity across consecutive frames and SHALL reacquire a hand on a subsequent valid frame after a brief loss without emitting a gesture command from the gap.

#### Scenario: Brief hand loss

- **WHEN** the tracked hand disappears briefly and then returns
- **THEN** the tracking identity is resumed or a new identity is issued, and no gesture event is generated for the gap

### Requirement: Resolution independence

Landmark and feature outputs SHALL be expressed in normalized coordinates independent of camera resolution so downstream gesture logic does not depend on pixel dimensions.

#### Scenario: Different camera resolutions

- **WHEN** the same hand pose is captured at 640x360 and at 1280x720
- **THEN** normalized landmark features remain comparable within the configured tolerance

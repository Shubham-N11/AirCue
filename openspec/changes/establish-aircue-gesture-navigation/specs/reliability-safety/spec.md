# Spec Delta

## Purpose

Keep AirCue safe and recoverable when tracking, camera, presentation focus, or the adapter degrades during a live presentation, and ensure every recovery ends in a safe state that requires deliberate reactivation.

## ADDED Requirements

### Requirement: Crash-free operation

The application SHALL handle recoverable faults without terminating and SHALL complete a 60-minute continuous session with zero unhandled crashes under the validation plan.

#### Scenario: Long session

- **WHEN** the application runs for 60 minutes with normal gesture activity
- **THEN** it remains running and reports no unhandled exception

#### Scenario: Recoverable fault

- **WHEN** a recoverable camera or adapter fault occurs
- **THEN** the application reports the fault and remains running

### Requirement: Tracking loss safety

Tracking loss SHALL follow interaction-state timing exactly. For the first 300 ms the pipeline SHALL freeze pointer, click, and scroll output without changing state. From 300 ms to 1,000 ms output SHALL stay frozen and no command SHALL be generated from the gap. Beyond 1,000 ms ACTIVE, POINTER_MODE, SCROLL_MODE, and PAUSED SHALL transition to IDLE; IDLE SHALL remain IDLE; ERROR and EXITING SHALL be unaffected.

#### Scenario: Brief occlusion

- **WHEN** the tracked hand is lost for less than 300 ms and then returns
- **THEN** output remains frozen during the loss and no command is emitted for the gap

#### Scenario: Extended loss

- **WHEN** the hand remains undetected for more than 1,000 ms
- **THEN** the application enters IDLE, cancels pending commands and clicks, and emits no command for the lost interval

#### Scenario: Recovery before IDLE

- **WHEN** the hand returns after a loss shorter than 1,000 ms
- **THEN** the state is unchanged, output stays frozen until gestures re-arm, and no command is replayed

#### Scenario: Recovery after IDLE

- **WHEN** the hand returns after tracking loss moved the application to IDLE
- **THEN** the application remains in IDLE until deliberate activation succeeds

### Requirement: Multiple hands

When more than one hand is visible, the system SHALL use only the primary hand and SHALL ignore gestures from all other hands.

#### Scenario: Two hands

- **WHEN** one primary hand is tracked and a second hand performs a fist
- **THEN** no pause command is emitted from the second hand

### Requirement: Poor lighting and motion blur

The system SHALL reject low-confidence landmark frames caused by poor lighting or motion blur and SHALL NOT emit commands from them.

#### Scenario: Low light

- **WHEN** landmark confidence falls below the configured threshold
- **THEN** no gesture command is emitted and degraded tracking is reported

### Requirement: Invalid landmark handling

The system SHALL reject missing, non-finite, or out-of-range landmark values without raising an unhandled exception or emitting a command.

#### Scenario: NaN landmarks

- **WHEN** a frame contains NaN or infinite landmark coordinates
- **THEN** the frame is discarded, counted as invalid, and processing continues with the next frame

### Requirement: Camera freeze and disconnection

When no frame arrives within 2,000 ms, the system SHALL treat the camera as faulted, suspend all command output, and transition any non-EXITING state to ERROR. It SHALL attempt a bounded reconnection with backoff, SHALL report each attempt, and SHALL keep the keyboard exit path available throughout.

#### Scenario: Camera disconnected

- **WHEN** no frame arrives within 2,000 ms
- **THEN** command output stops, the application enters ERROR, and bounded reconnection begins

#### Scenario: Reconnection succeeds

- **WHEN** the camera becomes available again within the bounded attempt window
- **THEN** the application returns to IDLE and requires deliberate activation

#### Scenario: Reconnection exhausted

- **WHEN** bounded reconnection attempts are exhausted
- **THEN** the application remains in ERROR, reports the failure, and continues to allow keyboard exit

### Requirement: Focus loss safety

When PowerPoint loses foreground focus, ACTIVE, POINTER_MODE, and SCROLL_MODE SHALL transition immediately to PAUSED, pending commands and clicks SHALL be canceled, and no input SHALL be sent to another application. Focus restoration alone SHALL NOT resume processing.

#### Scenario: Focus lost during presentation

- **WHEN** another application becomes foreground
- **THEN** navigation, pointer, click, and scroll output stop and the application enters PAUSED

#### Scenario: Focus returns

- **WHEN** the slideshow returns to the foreground while PAUSED
- **THEN** the application remains PAUSED until a deliberate thumbs-up resume succeeds

#### Scenario: No input to another application

- **WHEN** focus changes between validation and input synthesis
- **THEN** the adapter cancels the input and reports FOCUS_LOST

### Requirement: Presentation adapter failure

Adapter failures SHALL be reported to the state layer as structured errors, SHALL stop further dispatch of the failed command, and SHALL NOT crash or block the vision pipeline or the keyboard exit path.

#### Scenario: Recoverable adapter failure

- **WHEN** the adapter returns FOCUS_LOST, TARGET_CHANGED, TARGET_UNAVAILABLE, or UNSUPPORTED_PRESENTER_VIEW
- **THEN** the state layer enters PAUSED, cancels pending work, and requires deliberate resume

#### Scenario: Unrecoverable adapter failure

- **WHEN** the adapter returns INPUT_BLOCKED, ADAPTER_UNAVAILABLE, TIMEOUT, or INTERNAL
- **THEN** the state layer enters ERROR and stops dispatching presentation commands

### Requirement: Unresponsive adapter

If the adapter does not acknowledge a call within twice the 150 ms call deadline, the system SHALL mark it unresponsive, stop dispatch, and enter ERROR while keeping the state thread and keyboard exit path responsive.

#### Scenario: Adapter stops acknowledging

- **WHEN** the command worker has not acknowledged within 300 ms
- **THEN** the adapter is marked unresponsive, dispatch stops, and the application enters ERROR

#### Scenario: Exit during adapter hang

- **WHEN** the adapter is unresponsive and the exit shortcut is pressed
- **THEN** the application enters EXITING and attempts a bounded worker join without waiting indefinitely

### Requirement: Safe exit

The application SHALL provide a keyboard exit shortcut available in every non-terminated state. Gesture exit SHALL require a 1,500 ms sustained shaka hold; a single uncertain recognition SHALL NOT terminate the application.

#### Scenario: Emergency keyboard exit

- **WHEN** the exit shortcut is pressed in INITIALIZING, IDLE, ACTIVE, PAUSED, POINTER_MODE, SCROLL_MODE, or ERROR
- **THEN** the application enters EXITING, stops commands, releases resources, and terminates cleanly

#### Scenario: Uncertain shaka

- **WHEN** a shaka is detected ambiguously or briefly
- **THEN** the application continues running and emits no exit request

### Requirement: Resource cleanup

On exit, and when error recovery is exhausted or abandoned, the application SHALL stop accepting commands, cancel pending work, release the camera, Win32 resources, and presentation handles, join workers with bounded timeouts, close the status overlay last, and leave no orphaned process.

#### Scenario: Clean shutdown

- **WHEN** the application exits
- **THEN** the camera is released, the command worker is joined or logged as abandoned, the overlay closes last, and no child process remains

#### Scenario: Graceful shutdown timeout

- **WHEN** a worker does not stop within its join timeout
- **THEN** the forced abandonment is logged and the daemon worker cannot prevent process exit

### Requirement: Recovery to safe state

Recovery from ERROR SHALL return to IDLE through the transitions in design.md D3.1 and SHALL require deliberate activation. Recovery from a recoverable fault handled in PAUSED SHALL remain PAUSED until a deliberate thumbs-up resume succeeds. No recovery SHALL resume a previous interaction mode, replay a canceled command, or dispatch input merely because tracking returned.

#### Scenario: Recovery after error

- **WHEN** an ERROR condition is cleared by explicit reinitialization, or by a successful bounded camera reconnect when the cause was a camera fault
- **THEN** the application enters IDLE and waits for deliberate activation

#### Scenario: Recovery from a recoverable fault

- **WHEN** a recoverable adapter error is cleared
- **THEN** the application remains in PAUSED until deliberate resume

#### Scenario: No blind resume

- **WHEN** tracking returns after a fault
- **THEN** no pointer, scroll, click, or navigation command is emitted until activation or resume succeeds

### Requirement: Frame privacy

The system SHALL process camera frames in memory only and SHALL NOT record, persist, or transmit them unless debug capture is explicitly enabled by the user.

#### Scenario: Normal operation

- **WHEN** the application is running without debug capture
- **THEN** no camera image is written to disk or sent over a network

#### Scenario: Debug capture enabled

- **WHEN** the user explicitly enables debug capture
- **THEN** captured frames are stored locally in the configured debug directory and the opt-in is recorded

### Requirement: Fault observability

Every fault, recovery attempt, canceled command, and safe-state transition SHALL be recorded with a reason, severity, state generation, and monotonic timestamp.

#### Scenario: Fault recorded

- **WHEN** a camera or adapter fault occurs
- **THEN** a record with the fault reason, severity, state generation, and timestamp is written

#### Scenario: Recovery recorded

- **WHEN** a recovery attempt succeeds or fails
- **THEN** the attempt and outcome are recorded with the same session identifier

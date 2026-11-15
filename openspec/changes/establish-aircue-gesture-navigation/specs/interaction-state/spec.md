# Spec Delta

## Purpose

Own the application's operating mode, deliberate activation, and authoritative transitions so every command is validated and conflicting gestures cannot produce conflicting actions.

## ADDED Requirements

### Requirement: State set

The application SHALL implement exactly the states INITIALIZING, IDLE, ACTIVE, PAUSED, POINTER_MODE, SCROLL_MODE, EXITING, and ERROR.

#### Scenario: Startup

- **WHEN** the application starts
- **THEN** it enters INITIALIZING and remains there until initialization succeeds or fails

### Requirement: Authoritative transition table

The transition table in design.md D3.1 SHALL be the sole authority for state changes. The application SHALL permit only those transitions and SHALL reject every transition not listed there.

#### Scenario: Permitted transition

- **WHEN** a trigger listed for the current state occurs
- **THEN** the application performs exactly the listed target transition

#### Scenario: Unlisted transition

- **WHEN** a trigger is not listed for the current state
- **THEN** the application remains in the current state and records a rejection

#### Scenario: Direct mode switch

- **WHEN** a scroll-mode entry is requested while in POINTER_MODE
- **THEN** the transition is rejected and the application remains in POINTER_MODE

### Requirement: Initialization transitions

INITIALIZING SHALL transition to IDLE when camera, configuration, and adapter client initialization succeed, or to ERROR when a required component fails.

#### Scenario: Successful initialization

- **WHEN** camera capture, configuration, and the adapter client initialize successfully
- **THEN** the application transitions to IDLE and waits for deliberate activation

#### Scenario: Failed initialization

- **WHEN** a required component fails to initialize
- **THEN** the application transitions to ERROR and reports the failing component

### Requirement: Deliberate activation

IDLE SHALL transition to ACTIVE only after a deliberate thumbs-up hold of at least 800 ms or the activation hotkey, together with a confidently identified presentation target. Hand presence alone SHALL NOT activate the application.

#### Scenario: Hand present without activation gesture

- **WHEN** a valid hand is tracked in IDLE without a thumbs-up hold or activation hotkey
- **THEN** the application remains in IDLE

#### Scenario: Activation by gesture

- **WHEN** a thumbs-up is held for the activation window in IDLE with a valid target
- **THEN** the application transitions to ACTIVE

#### Scenario: Activation by keyboard

- **WHEN** the activation hotkey is pressed in IDLE with a valid target
- **THEN** the application transitions to ACTIVE

#### Scenario: Activation without a target

- **WHEN** activation is attempted while PowerPoint is in edit mode or the target is unknown
- **THEN** the application remains in IDLE and displays the reason

### Requirement: Capability gating

Mode entry and presentation commands SHALL be gated by the identified target's capabilities. Pointer, click, and scroll SHALL be unavailable in PRESENTER_VIEW, EDIT_MODE, and UNKNOWN targets.

#### Scenario: Presenter View activation

- **WHEN** activation succeeds with a PRESENTER_VIEW target
- **THEN** the application enters ACTIVE with navigation only

#### Scenario: Pointer entry in Presenter View

- **WHEN** a pinch is confirmed in ACTIVE with a PRESENTER_VIEW target
- **THEN** the application remains in ACTIVE and displays that pointer mode is unavailable

#### Scenario: Edit-mode activation

- **WHEN** activation is attempted with an EDIT_MODE target
- **THEN** the application remains in IDLE and displays that a slideshow is required

### Requirement: Visible status feedback

The application SHALL display a visible, non-activating status indicator showing the current state, target kind, available capabilities, activation prompt in IDLE, resume prompt in PAUSED, and fault reason in ERROR. The indicator SHALL NOT take foreground focus or intercept keyboard or mouse input.

#### Scenario: Activation prompt

- **WHEN** the application is in IDLE
- **THEN** the status indicator shows the activation gesture or hotkey and the current target kind

#### Scenario: Paused prompt

- **WHEN** the application is in PAUSED
- **THEN** the status indicator shows the resume gesture and the reason for pausing

#### Scenario: State change feedback

- **WHEN** the application changes state or mode
- **THEN** the status indicator updates to the new state or mode

#### Scenario: No focus theft

- **WHEN** the status indicator is visible while PowerPoint is foreground
- **THEN** PowerPoint remains the foreground application and keyboard input is unaffected

### Requirement: Tracking loss

Transient tracking loss SHALL freeze pointer, click, and scroll output without changing state. Continuous tracking loss beyond 1,000 ms SHALL move ACTIVE, POINTER_MODE, SCROLL_MODE, or PAUSED to IDLE. No command SHALL be generated from the lost interval.

#### Scenario: Brief tracking loss

- **WHEN** the tracked hand is lost for less than 300 ms and then returns
- **THEN** the state is unchanged and no command is emitted for the gap

#### Scenario: Extended tracking loss

- **WHEN** the hand remains undetected for more than 1,000 ms
- **THEN** the application enters IDLE and cancels pending commands

#### Scenario: Reacquisition before IDLE

- **WHEN** the hand returns after a loss shorter than 1,000 ms
- **THEN** pointer and scroll output remain frozen until gestures re-arm and no click or mode change is emitted from the gap

### Requirement: Focus loss

When PowerPoint loses foreground focus, ACTIVE, POINTER_MODE, and SCROLL_MODE SHALL transition immediately to PAUSED, pending commands SHALL be canceled, and no input SHALL be sent to another application. Resume SHALL require a thumbs-up after the target is foreground and revalidated.

#### Scenario: Focus lost during navigation

- **WHEN** another application becomes foreground while ACTIVE
- **THEN** the application enters PAUSED and cancels pending commands

#### Scenario: Focus returns without resume

- **WHEN** the slideshow returns to the foreground while PAUSED
- **THEN** the application remains PAUSED and sends no command

#### Scenario: Resume after focus recovery

- **WHEN** a thumbs-up is held for the resume window in PAUSED with the target foreground and revalidated
- **THEN** the application enters ACTIVE

### Requirement: Mode exclusivity

ACTIVE, POINTER_MODE, and SCROLL_MODE SHALL be mutually exclusive. POINTER_MODE and SCROLL_MODE SHALL be entered only from ACTIVE and SHALL exit only to ACTIVE, or to PAUSED, IDLE, EXITING, or ERROR for safety events. No direct POINTER_MODE to SCROLL_MODE or SCROLL_MODE to POINTER_MODE transition SHALL exist.

#### Scenario: Enter pointer mode

- **WHEN** a pinch is confirmed while ACTIVE
- **THEN** the application enters POINTER_MODE

#### Scenario: Enter scroll mode

- **WHEN** a peace sign is confirmed while ACTIVE
- **THEN** the application enters SCROLL_MODE

#### Scenario: Exit pointer mode

- **WHEN** a long pinch is confirmed while POINTER_MODE
- **THEN** the application enters ACTIVE and cancels any pending click

#### Scenario: Exit scroll mode

- **WHEN** a peace sign is confirmed while SCROLL_MODE
- **THEN** the application enters ACTIVE and stops scroll output

### Requirement: Pause semantics

PAUSED SHALL suspend all command processing except resume, exit, and keyboard fallback. A thumbs-up SHALL resume to ACTIVE, never to the previously active mode. Pause SHALL cancel pending clicks and commands.

#### Scenario: Pause from pointer mode

- **WHEN** a fist is confirmed in POINTER_MODE
- **THEN** the application enters PAUSED, cancels the pending click, and stops pointer output

#### Scenario: Resume

- **WHEN** a thumbs-up is held for the resume window in PAUSED with a valid target and focus
- **THEN** the application enters ACTIVE

### Requirement: Gesture priority

The application SHALL resolve simultaneous events in this order: exit, pause, resume or activation, mode exit, mode entry, slide navigation, click or double-click, scroll, pointer movement.

#### Scenario: Exit outranks all

- **WHEN** an exit request and any other event are pending together
- **THEN** only the exit transition is applied

#### Scenario: Pause outranks navigation

- **WHEN** pause and navigation events are pending in the same processing window
- **THEN** only the pause transition is applied

#### Scenario: Click outranks pointer movement

- **WHEN** a click candidate and pointer movement are pending in the same processing window
- **THEN** the click is arbitrated and pointer movement is suppressed for that window

### Requirement: Command gating

Every command SHALL be validated against the current state and target capabilities before dispatch. A command not available in that state or target SHALL have no presentation effect.

#### Scenario: Slide command while paused

- **WHEN** a slide navigation command is generated while PAUSED
- **THEN** no presentation action occurs and the rejection is recorded

#### Scenario: Pointer command while active

- **WHEN** a pointer movement command is generated while ACTIVE
- **THEN** no cursor movement occurs

#### Scenario: Click command in Presenter View

- **WHEN** a click command is generated with a PRESENTER_VIEW target
- **THEN** no click is dispatched and the rejection is recorded

### Requirement: State generation and stale work

Every accepted state transition SHALL increment a state generation. Pending commands and click candidates from an older generation SHALL be canceled before dispatch.

#### Scenario: Pause invalidates pending commands

- **WHEN** the application transitions from ACTIVE to PAUSED
- **THEN** all pending commands and click candidates from the ACTIVE generation are canceled

#### Scenario: Mode exit invalidates pending clicks

- **WHEN** POINTER_MODE exits to ACTIVE
- **THEN** any pending single or double click from that pointer-mode generation is canceled

### Requirement: Exit confirmation and shutdown

EXITING SHALL be entered only after the exit hotkey, a sustained shaka hold, or a shutdown signal. The application SHALL stop accepting commands, cancel pending work, release camera and Win32 resources, join workers with bounded timeouts, and then terminate.

#### Scenario: Deliberate exit

- **WHEN** the exit hotkey is pressed or a sustained shaka is accepted
- **THEN** the application enters EXITING, cancels pending commands, and releases resources

#### Scenario: Accidental exit attempt

- **WHEN** a brief or uncertain shaka is detected
- **THEN** the application remains in its current state

#### Scenario: Shutdown timeout

- **WHEN** a worker does not stop within its join timeout during EXITING
- **THEN** the forced abandonment is logged and the process terminates without leaving a child process

### Requirement: Error safe state

ERROR SHALL stop all presentation commands, report the failure, and permit recovery only through an explicit reinitialization or, when the error cause is a camera fault, a successful bounded camera reconnect. Recovery SHALL return to IDLE and SHALL require deliberate activation.

#### Scenario: Adapter timeout

- **WHEN** the adapter does not acknowledge a command within the unresponsive threshold
- **THEN** the application enters ERROR and stops dispatching commands

#### Scenario: Camera reconnect

- **WHEN** a camera fault is cleared by bounded reconnection
- **THEN** the application returns to IDLE and requires deliberate activation

#### Scenario: No automatic reactivation

- **WHEN** a hand is visible after ERROR recovery
- **THEN** no command is emitted until deliberate activation succeeds

### Requirement: Transition observability

Every accepted or rejected transition SHALL be recorded with the previous state, trigger, resulting state, reason, state generation, and monotonic timestamp.

#### Scenario: Rejected transition logged

- **WHEN** an invalid transition is rejected
- **THEN** a record containing the previous state, trigger, rejection reason, state generation, and timestamp is written

### Requirement: Keyboard shortcuts

The application SHALL provide configurable activation, deactivation, and exit shortcuts. Exit SHALL be available in every non-terminated state, including PAUSED and ERROR.

#### Scenario: Emergency exit

- **WHEN** the exit shortcut is pressed in any running state
- **THEN** the application enters EXITING and releases resources

#### Scenario: Deactivation

- **WHEN** the deactivation shortcut is pressed in ACTIVE, PAUSED, POINTER_MODE, or SCROLL_MODE
- **THEN** the application enters IDLE and cancels pending commands

#### Scenario: Activation outside IDLE

- **WHEN** the activation shortcut is pressed outside IDLE
- **THEN** the shortcut has no effect and the event is recorded

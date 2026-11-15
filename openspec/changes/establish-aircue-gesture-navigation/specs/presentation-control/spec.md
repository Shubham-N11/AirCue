# Spec Delta

## Purpose

Execute only validated presentation commands against a confidently identified PowerPoint target on Windows, with compatibility, focus, ordering, timeout, and failure rules that prevent input from reaching the wrong application or monitor.

## ADDED Requirements

### Requirement: Command boundary

The presentation adapter SHALL accept only validated semantic commands from the command layer and SHALL NOT read camera data or classify gestures.

#### Scenario: Ungated command

- **WHEN** a command is submitted without state validation
- **THEN** the adapter rejects it and performs no input action

### Requirement: PowerPoint discovery

The adapter SHALL detect running PowerPoint processes and SHALL report presentation control as unavailable when no supported process is found or process access fails.

#### Scenario: PowerPoint running

- **WHEN** a supported PowerPoint process is running
- **THEN** the adapter reports the process as available

#### Scenario: PowerPoint absent

- **WHEN** no PowerPoint process is running
- **THEN** the adapter reports unavailable without crashing

### Requirement: Presentation target identification

The adapter SHALL classify the presentation target as NORMAL_SLIDESHOW, PRESENTER_VIEW, EDIT_MODE, or UNKNOWN using process ownership, foreground status, visibility, window class/title signals, full-screen monitor bounds, and presenter-console/output pairing.

#### Scenario: Normal slideshow identified

- **WHEN** one PowerPoint slideshow window is foreground and covers one monitor
- **THEN** the target is classified as NORMAL_SLIDESHOW

#### Scenario: Presenter View identified

- **WHEN** a PowerPoint presenter console is foreground and a paired slideshow output is visible on another monitor
- **THEN** the target is classified as PRESENTER_VIEW

#### Scenario: Edit mode identified

- **WHEN** the foreground PowerPoint window is an editor with no slideshow output
- **THEN** the target is classified as EDIT_MODE

#### Scenario: Unknown configuration

- **WHEN** process ownership, window shape, or monitor pairing cannot be determined confidently
- **THEN** the target is classified as UNKNOWN

### Requirement: Normal slideshow behavior

For a NORMAL_SLIDESHOW target, navigation, pointer, click, and scroll commands SHALL be supported when the slideshow window is foreground and the command is valid for the current state.

#### Scenario: Full support in normal slideshow

- **WHEN** the target is NORMAL_SLIDESHOW and a valid pointer command arrives in POINTER_MODE
- **THEN** the cursor moves on the slideshow monitor

### Requirement: Presenter View behavior

For a PRESENTER_VIEW target, slide navigation SHALL be supported when the foreground window belongs to the same active presentation. Pointer, click, and scroll commands SHALL be rejected with UNSUPPORTED_PRESENTER_VIEW and SHALL send no input.

#### Scenario: Presenter View navigation

- **WHEN** a next-slide command is accepted with a PRESENTER_VIEW target
- **THEN** the presentation advances exactly one slide

#### Scenario: Presenter View pointer rejected

- **WHEN** a pointer command is submitted with a PRESENTER_VIEW target
- **THEN** no cursor movement is sent and UNSUPPORTED_PRESENTER_VIEW is returned

#### Scenario: Presenter View click rejected

- **WHEN** a click command is submitted with a PRESENTER_VIEW target
- **THEN** no click is sent and UNSUPPORTED_PRESENTER_VIEW is returned

#### Scenario: Presenter View scroll rejected

- **WHEN** a scroll command is submitted with a PRESENTER_VIEW target
- **THEN** no wheel input is sent and UNSUPPORTED_PRESENTER_VIEW is returned

### Requirement: Extended displays

When the slideshow is displayed on a secondary or extended monitor, navigation SHALL target the presentation window and pointer coordinates SHALL map to that monitor's bounds, not the primary monitor.

#### Scenario: Slideshow on secondary monitor

- **WHEN** the identified slideshow window covers a secondary monitor
- **THEN** pointer commands map to that monitor and navigation targets the slideshow

#### Scenario: Primary-monitor fallback prohibited

- **WHEN** the slideshow monitor cannot be identified
- **THEN** no pointer command is sent

### Requirement: Multiple monitors

The adapter SHALL accept a target only when exactly one candidate slideshow or presenter-output window can be paired with the active presentation. Multiple ambiguous candidates SHALL produce an UNKNOWN target.

#### Scenario: Ambiguous slideshow candidates

- **WHEN** two full-screen PowerPoint windows could be the active slideshow
- **THEN** the target is UNKNOWN and no input is sent

#### Scenario: Single unambiguous candidate

- **WHEN** exactly one slideshow output and one presenter console belong to the same presentation
- **THEN** the presenter target is accepted for navigation

### Requirement: Edit mode rejection

For an EDIT_MODE target, the adapter SHALL reject activation, navigation, pointer, click, and scroll commands and SHALL send no input.

#### Scenario: Navigation in edit mode

- **WHEN** a previous-slide command is submitted while PowerPoint is in edit mode
- **THEN** no slide action occurs, the target remains EDIT_MODE, and the rejection is recorded

### Requirement: Unknown target fail-closed

For an UNKNOWN target, the adapter SHALL send no input and SHALL return TARGET_UNAVAILABLE. Diagnostics SHALL list candidate process, window class, title, foreground status, and monitor bounds.

#### Scenario: Unknown target rejection

- **WHEN** a command is submitted with an UNKNOWN target
- **THEN** no input is sent, TARGET_UNAVAILABLE is returned, and a diagnostic record is produced

### Requirement: Target snapshot freshness

The adapter SHALL expose a target snapshot containing process ID, window handle or handles, target kind, capabilities, monitor bounds, and capture time. A snapshot older than 1,000 ms SHALL be treated as UNKNOWN, SHALL produce TARGET_UNAVAILABLE, and SHALL send no input.

#### Scenario: Fresh snapshot

- **WHEN** the state layer requests presentation status
- **THEN** the adapter returns the latest target kind, capabilities, monitor bounds, and timestamp

#### Scenario: Stale snapshot

- **WHEN** the latest snapshot is older than 1,000 ms
- **THEN** the target is treated as UNKNOWN, no command is dispatched, and the state layer enters PAUSED with a target-unavailable reason

### Requirement: Target revalidation

Every input SHALL be preceded by revalidation of process ID, window handle, target kind, foreground status, and monitor bounds. A changed target SHALL cause TARGET_CHANGED or FOCUS_LOST and SHALL send no input.

#### Scenario: Focus changes during dispatch

- **WHEN** the foreground window changes after validation but before input synthesis
- **THEN** the adapter cancels the input and returns FOCUS_LOST

#### Scenario: Window handle changes

- **WHEN** the slideshow window handle changes before synthesis
- **THEN** the adapter returns TARGET_CHANGED and sends no input

### Requirement: Focus validation

Input synthesis SHALL occur only when the intended PowerPoint target is foreground. Focus loss SHALL stop dispatch and require deliberate resume; focus restoration alone SHALL NOT dispatch a queued command.

#### Scenario: Focus lost

- **WHEN** the target loses foreground focus
- **THEN** no input is synthesized and the state layer is notified

#### Scenario: Focus restored without resume

- **WHEN** the target returns to the foreground while PAUSED
- **THEN** no command is dispatched until a deliberate resume occurs

### Requirement: Slide navigation exactly once

Each accepted next-slide or previous-slide command SHALL produce exactly one slide transition and SHALL NOT repeat while the triggering gesture remains active.

#### Scenario: Single navigation event

- **WHEN** one NEXT_SLIDE command is dispatched
- **THEN** PowerPoint advances exactly one slide

#### Scenario: Held gesture

- **WHEN** the navigation gesture remains active after one dispatch
- **THEN** no additional slide transition occurs until a new validated event arrives

### Requirement: Pointer movement

Pointer commands SHALL move the system cursor to the requested screen coordinate only while POINTER_MODE is active, the target is NORMAL_SLIDESHOW, and the target is foreground.

#### Scenario: Pointer movement

- **WHEN** a valid pointer position arrives in POINTER_MODE with a focused normal slideshow
- **THEN** the cursor moves to the mapped slideshow-monitor coordinate

#### Scenario: Pointer command without focus

- **WHEN** a pointer command arrives while the target lacks foreground focus
- **THEN** the cursor is not moved

### Requirement: Click and double-click

Click commands SHALL synthesize one left-button click at the current cursor position, and double-click commands SHALL synthesize one double-click, only while POINTER_MODE is active, the target is NORMAL_SLIDESHOW, and the target is foreground.

#### Scenario: Single click

- **WHEN** a CLICK command is accepted
- **THEN** one left-button click is synthesized

#### Scenario: Double click

- **WHEN** a DOUBLE_CLICK command is accepted
- **THEN** one double-click is synthesized without an extra single click

#### Scenario: Click in a non-normal target

- **WHEN** a click command is submitted for PRESENTER_VIEW, EDIT_MODE, or UNKNOWN
- **THEN** no click is synthesized

### Requirement: Scroll

Scroll commands SHALL synthesize vertical mouse-wheel input only while SCROLL_MODE is active, the target is NORMAL_SLIDESHOW, and the target is foreground, using the direction and amount supplied by the command.

#### Scenario: Scroll up

- **WHEN** a scroll-up command is accepted
- **THEN** the adapter emits upward wheel input matching the requested amount

#### Scenario: Scroll without focus

- **WHEN** a scroll command arrives while the target lacks foreground focus
- **THEN** no wheel input is emitted

### Requirement: Bounded command dispatch

The adapter SHALL execute commands through one command worker in FIFO order. Each command SHALL carry a sequence number, state generation, target snapshot, enqueue time, and expiry time. Adjacent pointer moves may be coalesced, but pointer moves SHALL NOT be reordered across clicks, navigation, or scroll.

#### Scenario: Ordering preserved

- **WHEN** a pointer move, then a click, then a navigation command are enqueued
- **THEN** the worker executes them in that order

#### Scenario: Pointer coalescing

- **WHEN** consecutive pointer moves are queued with no intervening non-pointer command
- **THEN** the newest pointer position may replace the older one

#### Scenario: Coalescing prohibited across click

- **WHEN** a pointer move is queued before a click and another pointer move after it
- **THEN** no pointer move is reordered across the click

### Requirement: Command freshness and deadlines

Every command SHALL have a configurable time-to-live and adapter call deadline. An expired command SHALL be rejected as STALE_COMMAND, SHALL NOT be executed, and SHALL NOT change application state. An adapter call exceeding its deadline SHALL return TIMEOUT and SHALL NOT be retried.

#### Scenario: Stale navigation command

- **WHEN** a navigation command remains queued beyond its time-to-live
- **THEN** it is rejected as STALE_COMMAND, no slide action occurs, and the application state is unchanged

#### Scenario: Adapter call timeout

- **WHEN** an adapter call exceeds its deadline
- **THEN** TIMEOUT is reported and the command is not retried

### Requirement: State-change cancellation

Every accepted state transition SHALL invalidate pending commands and click candidates from the previous state generation. The worker SHALL check the generation before input synthesis and skip invalidated work.

#### Scenario: Pause cancels queued work

- **WHEN** the application transitions to PAUSED
- **THEN** queued commands from the previous generation are canceled before dispatch

#### Scenario: Mode exit cancels click

- **WHEN** POINTER_MODE exits to ACTIVE with a click command queued
- **THEN** the click is canceled and no input is sent

### Requirement: Unresponsive adapter recovery

The adapter SHALL report a heartbeat or acknowledgement for each call. If no acknowledgement arrives within twice the call deadline, the adapter SHALL be marked unresponsive, dispatch SHALL stop, and the application SHALL enter ERROR. The state thread and keyboard exit path SHALL remain responsive.

#### Scenario: Unresponsive adapter

- **WHEN** the command worker has not acknowledged within twice the call deadline
- **THEN** the adapter is marked unresponsive, dispatch stops, and the application enters ERROR

#### Scenario: Exit remains available

- **WHEN** the adapter is unresponsive
- **THEN** the keyboard exit path still works and shutdown is attempted with a bounded join

### Requirement: Structured error mapping

Adapter failures SHALL be returned as structured errors. FOCUS_LOST, TARGET_CHANGED, TARGET_UNAVAILABLE, and UNSUPPORTED_PRESENTER_VIEW SHALL map to PAUSED; STALE_COMMAND SHALL be dropped and counted without a state transition; INPUT_BLOCKED, ADAPTER_UNAVAILABLE, TIMEOUT, and INTERNAL SHALL map to ERROR.

#### Scenario: Recoverable focus failure

- **WHEN** the adapter returns FOCUS_LOST
- **THEN** the state layer enters PAUSED and cancels pending work

#### Scenario: Unrecoverable input failure

- **WHEN** the adapter returns INPUT_BLOCKED
- **THEN** the state layer enters ERROR

### Requirement: Input isolation

The adapter SHALL NOT send input to any window other than the validated PowerPoint target, including when focus changes between validation and dispatch.

#### Scenario: Focus changes during dispatch

- **WHEN** another application becomes foreground after validation but before input synthesis
- **THEN** the adapter revalidates and cancels the input

### Requirement: PowerPoint closure

When PowerPoint exits while the adapter is attached, the adapter SHALL report ADAPTER_UNAVAILABLE, send no further input, and the state layer SHALL enter ERROR.

#### Scenario: PowerPoint closes mid-presentation

- **WHEN** PowerPoint exits while the adapter is attached
- **THEN** the adapter reports ADAPTER_UNAVAILABLE and the state layer enters ERROR

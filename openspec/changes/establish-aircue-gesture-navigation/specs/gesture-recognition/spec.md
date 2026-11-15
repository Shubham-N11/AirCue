# Spec Delta

## Purpose

Turn validated hand landmarks into a fixed, context-sensitive gesture vocabulary using geometric criteria, temporal confirmation, debounce, and cooldown so only deliberate gestures become semantic events.

## ADDED Requirements

### Requirement: Fixed gesture vocabulary

The recognizer SHALL support exactly these gestures: open-palm clockwise and counterclockwise wrist rotation, closed fist, thumbs-up, pinch, index-finger-plus-thumb pointer pose, pinch release, peace sign, and shaka.

#### Scenario: Supported gesture set

- **WHEN** the recognizer is initialized
- **THEN** its published vocabulary contains exactly the nine configured gestures and no unlisted gesture can produce an event

### Requirement: Semantic event output

Gesture recognition SHALL emit semantic gesture events only and SHALL NOT execute presentation actions, move the cursor, or synthesize input. Each candidate SHALL carry an onset timestamp, onset frame sequence, and confidence.

#### Scenario: Recognized fist

- **WHEN** a closed fist is confirmed
- **THEN** a PAUSE_TRACKING semantic event is emitted to the state layer
- **AND** no presentation command is executed by the recognizer

#### Scenario: Onset metadata

- **WHEN** a gesture candidate is confirmed
- **THEN** its event includes the first frame and timestamp at which its onset predicate became true

### Requirement: Context-sensitive thumbs-up

A thumbs-up SHALL emit ACTIVATE when held for 800 ms in IDLE, RESUME_TRACKING when held for 250 ms in PAUSED, and no event in ACTIVE, POINTER_MODE, or SCROLL_MODE.

#### Scenario: Activation in IDLE

- **WHEN** a thumbs-up is held for 800 ms in IDLE
- **THEN** ACTIVATE is emitted

#### Scenario: Resume in PAUSED

- **WHEN** a thumbs-up is held for 250 ms in PAUSED
- **THEN** RESUME_TRACKING is emitted

#### Scenario: Thumbs-up outside activation or resume

- **WHEN** a thumbs-up is confirmed in ACTIVE
- **THEN** no event is emitted

### Requirement: Context-sensitive fist

A closed fist SHALL emit PAUSE_TRACKING in ACTIVE, POINTER_MODE, or SCROLL_MODE, and SHALL emit no event in IDLE or PAUSED.

#### Scenario: Pause in pointer mode

- **WHEN** a closed fist is confirmed in POINTER_MODE
- **THEN** PAUSE_TRACKING is emitted

#### Scenario: Fist while paused

- **WHEN** a closed fist is confirmed in PAUSED
- **THEN** no event is emitted

### Requirement: Temporal confirmation for static gestures

Static gestures SHALL require continuous detection for a configured confirmation window before emitting an event, and SHALL be cancelled if the pose changes before the window elapses.

#### Scenario: Brief fist

- **WHEN** a closed fist is detected for less than the confirmation window
- **THEN** no pause event is emitted

#### Scenario: Sustained fist

- **WHEN** a closed fist remains stable for the confirmation window
- **THEN** exactly one pause event is emitted

### Requirement: Debounce and re-arm

Each gesture SHALL have a cooldown and SHALL re-arm only after the hand returns to a neutral or different pose, preventing repeated events from one continuous pose.

#### Scenario: Long-held fist

- **WHEN** a closed fist remains held for several seconds
- **THEN** only one pause event is emitted until the fist is released and the hand re-arms

#### Scenario: Rapid repeated gesture

- **WHEN** the same gesture is performed twice within its cooldown
- **THEN** the second activation is suppressed

### Requirement: Low-confidence rejection

Gesture candidates whose landmark confidence, pose completeness, or temporal stability falls below configured thresholds SHALL be discarded without emitting an event.

#### Scenario: Uncertain thumbs-up

- **WHEN** a thumbs-up is partially occluded and its confidence is below threshold
- **THEN** no activation or resume event is emitted

### Requirement: Slide navigation rotation

An open palm rotating past a configurable angular threshold SHALL emit one NEXT_SLIDE event for clockwise rotation or one PREV_SLIDE event for counterclockwise rotation, using a neutral orientation as the starting reference.

#### Scenario: Clockwise rotation

- **WHEN** an open palm rotates clockwise beyond the activation threshold from neutral
- **THEN** exactly one NEXT_SLIDE event is emitted

#### Scenario: Counterclockwise rotation

- **WHEN** an open palm rotates counterclockwise beyond the activation threshold from neutral
- **THEN** exactly one PREV_SLIDE event is emitted

### Requirement: Rotation jitter suppression

Rotation events SHALL require a minimum angular displacement and SHALL be suppressed when wrist-angle changes are within the tracking-jitter band.

#### Scenario: Tracking jitter

- **WHEN** wrist angle oscillates within the jitter band
- **THEN** no slide navigation event is emitted

### Requirement: Continuous rotation

When continuous rotation is enabled, further rotation past the activation threshold SHALL repeat the same navigation event at a configured interval up to a maximum rate, and SHALL stop when the hand returns to neutral, direction reverses, or the gesture is lost.

#### Scenario: Deliberate continuous rotation

- **WHEN** the open palm continues rotating clockwise past the repeat threshold while continuous rotation is enabled
- **THEN** NEXT_SLIDE repeats no faster than the configured maximum rate

#### Scenario: Return to neutral

- **WHEN** the palm returns to neutral during continuous rotation
- **THEN** repetition stops and the gesture re-arms

### Requirement: Pinch initiation and release

A pinch SHALL be initiated when the thumb-tip to index-tip distance is below 0.22 palm units for 100 ms, released when it is above 0.32 for 100 ms, and re-armed only after it is above 0.40 for 300 ms. Required landmarks SHALL be present and valid.

#### Scenario: Pinch initiation

- **WHEN** thumb-tip to index-tip distance remains below 0.22 palm units for 100 ms
- **THEN** the pinch enters the closed state

#### Scenario: Hysteresis prevents chatter

- **WHEN** the distance oscillates between 0.22 and 0.32 palm units
- **THEN** no new initiation or release event is emitted

#### Scenario: Re-arm after release

- **WHEN** the pinch releases and the distance remains above 0.40 palm units for 300 ms
- **THEN** the next pinch cycle can begin

#### Scenario: Partial occlusion

- **WHEN** the thumb or index fingertip is missing or below confidence threshold
- **THEN** no pinch initiation or release is emitted

### Requirement: Pointer pose geometry

The pointer pose SHALL require an extended index finger, an extended thumb, thumb-tip to index-tip separation above 0.40 palm units, curled middle, ring, and little fingers, and valid confident landmarks. The pointer source SHALL be the index fingertip.

#### Scenario: Valid pointer pose

- **WHEN** the index and thumb are extended and separated while the other fingers are curled
- **THEN** the pose is valid for pointer movement

#### Scenario: Pointer pose with insufficient separation

- **WHEN** the thumb-tip to index-tip separation is at or below 0.40 palm units
- **THEN** the pose is not a valid pointer pose

#### Scenario: Occluded pointer pose

- **WHEN** any required pointer landmark is missing or below confidence threshold
- **THEN** no pointer position update is emitted

### Requirement: Pointer mode entry consumes the pinch

A pinch confirmed in ACTIVE SHALL emit ENTER_POINTER_MODE and SHALL be consumed. If the target lacks pointer capability, the state layer SHALL reject the mode entry and report the reason, and the pinch SHALL still produce no click. That pinch cycle SHALL NOT produce a click before release and re-arm.

#### Scenario: Entry pinch is consumed

- **WHEN** a pinch confirmed in ACTIVE enters POINTER_MODE
- **THEN** the pinch is consumed and no click candidate is emitted from it

#### Scenario: Entry pinch without pointer capability

- **WHEN** a pinch is confirmed in ACTIVE with a target that lacks pointer capability
- **THEN** the mode entry is rejected with feedback and the pinch still produces no click

#### Scenario: First click after entry

- **WHEN** the entry pinch is released, re-armed, and followed by a new pinch-release cycle
- **THEN** one click candidate may be emitted

### Requirement: Long pinch priority

A pinch held closed for at least 700 ms in POINTER_MODE SHALL emit EXIT_POINTER_MODE, SHALL cancel any pending click, and SHALL suppress the click that would otherwise occur on release.

#### Scenario: Long pinch exits pointer mode

- **WHEN** a pinch remains closed for 700 ms in POINTER_MODE
- **THEN** EXIT_POINTER_MODE is emitted

#### Scenario: Long pinch suppresses click

- **WHEN** a pinch crosses the 700 ms threshold and is then released
- **THEN** no click candidate is emitted

### Requirement: Click candidate emission

In POINTER_MODE, a valid pinch release before the long-pinch threshold SHALL emit CLICK_CANDIDATE rather than CLICK. The click candidate's onset SHALL be the first frame of the release predicate, not the pinch closure. The click arbiter SHALL treat a second CLICK_CANDIDATE within the 350 ms double-click window as a double-click; otherwise it emits a single click after the window expires.

#### Scenario: Single click candidate

- **WHEN** one valid pinch release occurs in POINTER_MODE
- **THEN** one CLICK_CANDIDATE event is emitted with its release onset timestamp

#### Scenario: Double click

- **WHEN** two CLICK_CANDIDATE events occur within the 350 ms window
- **THEN** the arbiter emits one DOUBLE_CLICK and cancels the pending single click

### Requirement: Pointer position updates

POINTER_POSITION updates SHALL be emitted only in POINTER_MODE when the pointer pose is valid, no pinch is closed, and no click is pending. Pointer movement alone SHALL NOT emit clicks or mode changes.

#### Scenario: Pointer movement

- **WHEN** the pointer pose moves while no pinch is closed and no click is pending
- **THEN** pointer position updates are emitted

#### Scenario: Pointer movement during pinch

- **WHEN** a pinch is closed or a click is pending
- **THEN** pointer position updates are suppressed

#### Scenario: Pointer movement is not a click

- **WHEN** the pointer pose moves without a pinch cycle
- **THEN** no click or mode event is emitted

### Requirement: Scroll gesture

A peace sign SHALL emit ENTER_SCROLL_MODE when confirmed in ACTIVE and SHALL emit EXIT_SCROLL_MODE when confirmed in SCROLL_MODE. A peace sign in POINTER_MODE SHALL emit no mode transition.

#### Scenario: Enter scroll mode

- **WHEN** a peace sign is confirmed while ACTIVE
- **THEN** ENTER_SCROLL_MODE is emitted

#### Scenario: Exit scroll mode

- **WHEN** a peace sign is confirmed while SCROLL_MODE
- **THEN** EXIT_SCROLL_MODE is emitted

#### Scenario: Peace sign in pointer mode

- **WHEN** a peace sign is confirmed while POINTER_MODE
- **THEN** no mode transition is emitted

### Requirement: Exit gesture

A shaka gesture SHALL emit EXIT_REQUEST only after a deliberate continuous hold of 1,500 ms in IDLE, ACTIVE, PAUSED, POINTER_MODE, SCROLL_MODE, or ERROR when hand tracking is available. Releasing before the hold completes SHALL cancel the request.

#### Scenario: Short shaka

- **WHEN** a shaka is detected for less than the exit-hold window
- **THEN** no EXIT_REQUEST is emitted

#### Scenario: Sustained shaka

- **WHEN** a shaka remains stable for the exit-hold window
- **THEN** one EXIT_REQUEST is emitted

#### Scenario: Exit from error with tracking

- **WHEN** a shaka is held for the exit-hold window in ERROR while hand tracking is available
- **THEN** EXIT_REQUEST is emitted

### Requirement: Gesture priority

When multiple gesture candidates are valid in the same frame, the recognizer SHALL emit only the highest-priority candidate in this order: exit, pause, resume or activation, mode exit, mode entry, slide navigation, click or double-click, scroll, pointer movement.

#### Scenario: Fist and rotation together

- **WHEN** a closed fist and an open-palm rotation are both detected
- **THEN** only the pause gesture is emitted

#### Scenario: Exit and anything else

- **WHEN** an exit request and any other gesture are both detected
- **THEN** only the exit request is emitted

#### Scenario: Click and pointer movement

- **WHEN** a click candidate and pointer movement are both detected
- **THEN** the click candidate is emitted and pointer movement is suppressed for that window

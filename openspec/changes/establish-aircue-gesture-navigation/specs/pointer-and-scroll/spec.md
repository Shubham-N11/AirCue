# Spec Delta

## Purpose

Map tracked hand movement into stable cursor motion, deliberate click semantics, and scroll behavior on the PowerPoint slideshow display, including the intentional delay required for double-click recognition.

## ADDED Requirements

### Requirement: Pointer coordinate mapping

While in POINTER_MODE, the system SHALL map the valid pointer source's normalized position to the bounds of the monitor containing the identified slideshow window, preserving aspect ratio and applying a configurable sensitivity. It SHALL NOT default to the primary monitor when the slideshow is elsewhere.

#### Scenario: Extended-display slideshow

- **WHEN** the slideshow is on a secondary monitor and pointer mode is active
- **THEN** the cursor traverses that monitor's bounds

#### Scenario: Different display resolutions

- **WHEN** the same normalized pointer position is used on a 1280x720 and a 1920x1080 slideshow monitor
- **THEN** the cursor lands at the corresponding proportional location

#### Scenario: Ambiguous monitor target

- **WHEN** the slideshow monitor cannot be identified confidently
- **THEN** no pointer movement is emitted

### Requirement: Neutral region

The system SHALL define a neutral region and configurable active range so small hand movements near the neutral pose do not move the cursor.

#### Scenario: Movement inside neutral region

- **WHEN** the pointer source stays within the neutral region
- **THEN** the cursor does not move

### Requirement: Cursor stabilization

The system SHALL apply adaptive smoothing and a configurable dead zone that reduce cursor jitter without adding more than the configured maximum latency.

#### Scenario: Stationary hand

- **WHEN** the hand is held stationary within tracking noise
- **THEN** cursor jitter remains within the configured pixel tolerance

#### Scenario: Deliberate fast movement

- **WHEN** the hand moves rapidly across the active range
- **THEN** the cursor follows without exceeding the configured smoothing latency

### Requirement: Pointer freeze on loss

When the pointer source is lost or invalid, the system SHALL freeze the cursor at its last valid position and SHALL resume from that position without a jump when tracking returns and gestures re-arm.

#### Scenario: Temporary pointer loss

- **WHEN** the pointer source disappears for a short interval
- **THEN** the cursor remains at its last valid position

#### Scenario: Pointer reacquisition

- **WHEN** tracking returns after a brief loss
- **THEN** cursor movement resumes from the frozen position without teleporting

### Requirement: Pointer movement preconditions

Pointer movement SHALL be emitted only in POINTER_MODE, with a valid pointer pose, valid target capability, no closed pinch, and no pending click. Pointer movement alone SHALL NOT produce a click, mode change, or scroll.

#### Scenario: Valid movement

- **WHEN** the pointer pose moves in POINTER_MODE with no pinch closed and no click pending
- **THEN** cursor movement is emitted

#### Scenario: Movement during pinch

- **WHEN** a pinch is closed
- **THEN** pointer movement is suppressed

#### Scenario: Movement during pending click

- **WHEN** a click candidate is waiting for the double-click window to expire
- **THEN** pointer movement is frozen

#### Scenario: Movement cannot click

- **WHEN** the pointer pose moves without a pinch cycle
- **THEN** no click is emitted

### Requirement: Click arbitration

A valid pinch release in POINTER_MODE SHALL create a pending single click and start a 350 ms double-click window. A second valid candidate within the window SHALL dispatch one double-click immediately and cancel the pending single click; otherwise the single click SHALL dispatch when the window expires. This intentionally delays single clicks by up to 350 ms after the 100 ms release confirmation.

#### Scenario: Single click after window

- **WHEN** one click candidate occurs and no second candidate arrives within 350 ms
- **THEN** exactly one single click is dispatched at window expiry

#### Scenario: Double click within window

- **WHEN** a second click candidate arrives within 350 ms
- **THEN** exactly one double-click is dispatched immediately and the pending single click is canceled

#### Scenario: Pointer stays frozen

- **WHEN** a single click is pending
- **THEN** the cursor remains at the release position until dispatch or cancellation

### Requirement: Pending click cancellation

A pending click SHALL be canceled without dispatch when tracking is lost, the pointer pose becomes invalid, presentation focus is lost, the state or mode changes, a long pinch occurs, or the target becomes unavailable.

#### Scenario: Focus lost during pending click

- **WHEN** PowerPoint loses focus while a single click is pending
- **THEN** the pending click is canceled and no click is dispatched

#### Scenario: Tracking lost during pending click

- **WHEN** the pointer becomes invalid while a single click is pending
- **THEN** the pending click is canceled

#### Scenario: Mode change during pending click

- **WHEN** POINTER_MODE exits before the window expires
- **THEN** the pending click is canceled

### Requirement: Pinch click cycle

Clicks SHALL use the pinch initiation, release, and re-arm thresholds defined by gesture-recognition. A click candidate SHALL require a confirmed close, a confirmed release before the long-pinch threshold, and a fully re-armed pinch cycle. A continuous pinch SHALL NOT produce repeated clicks.

#### Scenario: Confirmed click

- **WHEN** a pinch closes, releases, and the cycle re-arms
- **THEN** one click candidate may be produced

#### Scenario: Held pinch

- **WHEN** a pinch remains closed without release
- **THEN** no click is emitted

#### Scenario: Entry pinch

- **WHEN** a pinch is consumed to enter POINTER_MODE
- **THEN** that pinch cycle produces no click

### Requirement: Long pinch priority

A long pinch SHALL exit POINTER_MODE before any click is dispatched, SHALL cancel a pending click, and SHALL suppress the click that would otherwise occur on release.

#### Scenario: Long pinch while click pending

- **WHEN** a pinch remains closed for 700 ms while a single click is pending
- **THEN** the pending click is canceled and POINTER_MODE exits

#### Scenario: Release after long pinch

- **WHEN** a long pinch is released after the threshold
- **THEN** no click is dispatched

### Requirement: Click capability and focus gating

A click SHALL be dispatched only when the target reports click capability, the application is in POINTER_MODE, and the slideshow has foreground focus. Otherwise the click SHALL be rejected or canceled.

#### Scenario: Presenter View click

- **WHEN** a click candidate is produced with a PRESENTER_VIEW target
- **THEN** no click is dispatched

#### Scenario: Click without focus

- **WHEN** a click candidate is produced while PowerPoint lacks foreground focus
- **THEN** no click is dispatched

### Requirement: Scroll activation

Scroll output SHALL be available only in SCROLL_MODE with a target that reports scroll capability. Entering or leaving scroll mode SHALL NOT emit scroll events by itself.

#### Scenario: Enter scroll mode

- **WHEN** SCROLL_MODE is entered
- **THEN** no scroll event is emitted until deliberate hand movement occurs

#### Scenario: Scroll outside scroll mode

- **WHEN** vertical hand movement occurs in ACTIVE
- **THEN** no scroll event is emitted

#### Scenario: Scroll in Presenter View

- **WHEN** SCROLL_MODE is requested with a PRESENTER_VIEW target
- **THEN** the mode entry is rejected

### Requirement: Scroll mapping

In SCROLL_MODE, vertical displacement of the tracked hand from its neutral position SHALL map to mouse-wheel scrolling with configurable direction and speed, subject to a dead zone and maximum rate.

#### Scenario: Upward scroll

- **WHEN** the hand moves upward beyond the scroll dead zone
- **THEN** the system emits upward wheel events at a rate proportional to displacement up to the configured maximum

#### Scenario: Scroll dead zone

- **WHEN** the hand remains within the scroll dead zone
- **THEN** no scroll events are emitted

### Requirement: Scroll stop

Scrolling SHALL stop when the hand returns to the scroll dead zone, leaves SCROLL_MODE, is lost, or presentation focus is lost.

#### Scenario: Hand lost during scroll

- **WHEN** the tracked hand disappears while scrolling
- **THEN** scroll emission stops immediately

#### Scenario: Mode exit during scroll

- **WHEN** SCROLL_MODE is exited
- **THEN** no further scroll events are emitted

#### Scenario: Focus lost during scroll

- **WHEN** PowerPoint loses foreground focus while scrolling
- **THEN** scroll emission stops immediately

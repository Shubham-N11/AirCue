# PowerPoint compatibility matrix — manual worksheet (task 5.9)

Status: **not yet run.** No result below may be copied into
`docs/presentation-integration.md` (task 5.10) until it has been observed on real
hardware. The final document is written after task 7.1 provides `aircue diagnose`
and `aircue run`.

## Prerequisites

- Windows 10 or 11, 64-bit, with the exact build noted.
- PowerPoint desktop 2019, 2021, and Microsoft 365, **64-bit**. Record the full
  build from **File > Account > About PowerPoint** for each.
- A standard webcam and the AirCue app started with `aircue run`.
- Display layouts:
  - single monitor;
  - extended display with the slideshow on the secondary monitor;
  - any additional monitors you have, including mirrored or duplicate mode.
- Record each monitor's resolution, scale, and position relative to the primary.
- Do not run AirCue elevated except in the UIPI scenario below.

## Per-version header

| Field | Value |
|---|---|
| Date | |
| Tester | |
| Windows edition/build | |
| PowerPoint product | 2019 / 2021 / Microsoft 365 |
| PowerPoint version/build | |
| Display layout | single / extended / mirrored |
| Monitors (resolution, scale, arrangement) | |
| Slideshow monitor | |

## Scenarios

Run every scenario for every PowerPoint version. Paste the `aircue diagnose`
output for each scenario into the notes column; it must list candidate process,
window class, title, foreground status, and monitor bounds.

### 1. Normal slideshow, single monitor

1. Open a deck and start **Slide Show > From Beginning**.
2. Run `aircue diagnose`. Expect target kind `NORMAL_SLIDESHOW`; record the
   monitor bounds.
3. Activate AirCue deliberately (thumbs-up 800 ms or `Ctrl+Alt+A`).
4. Perform next-slide once. Expect exactly one slide advance.
5. Hold the next-slide gesture. Expect no repeat until a new validated event.
6. Perform previous-slide once. Expect exactly one slide back.
7. Enter POINTER_MODE. Move the hand across the frame. Expect the cursor on the
   slideshow monitor only.
8. Click once. Expect one left click. Double-click. Expect one double-click and
   no extra single click.
9. Scroll up and down. Expect wheel movement in the requested direction only.

### 2. Normal slideshow, extended display

1. Move the slideshow to the secondary monitor and start it.
2. `aircue diagnose` must report `NORMAL_SLIDESHOW` with the **secondary**
   monitor bounds, not the primary monitor.
3. Move the pointer to all four corners of the camera frame. Expect clamped
   cursor positions inside the slideshow monitor with no primary-monitor fallback.
4. Repeat next, previous, click, double-click, and scroll.

### 3. Presenter View, extended display

1. Start Presenter View with the console on the primary monitor and the output
   on the secondary monitor.
2. `aircue diagnose` must report `PRESENTER_VIEW` with navigation capability only.
3. Next and previous must be accepted.
4. Pointer move, click, double-click, and scroll must be rejected with
   `UNSUPPORTED_PRESENTER_VIEW`, and no input may be observed in PowerPoint.
5. Alt-tab between the console and the output (when the console allows it).
   Expect the paired target to remain valid; record any `TARGET_CHANGED` result.

### 4. Multiple monitors and ambiguity

1. With three or more monitors, or two slideshow-like windows, arrange the deck
   so classification is ambiguous.
2. `aircue diagnose` must report `UNKNOWN` and list every candidate.
3. Every command must be rejected and no input sent.
4. Repeat in mirrored/duplicate display mode and record the observed kind.

### 5. Edit mode

1. Return to the PowerPoint editor with no slideshow running.
2. `aircue diagnose` must report `EDIT_MODE`.
3. Attempt activation (thumbs-up and `Ctrl+Alt+A`). Activation must be rejected.
4. Attempt every gesture. No input may reach the editor.

### 6. Foreground application changes

1. During a normal slideshow, alt-tab to another application.
2. Expect `FOCUS_LOST`, a transition to `PAUSED`, and no queued command firing.
3. Return PowerPoint to the foreground. Expect no dispatch until a deliberate
   resume (thumbs-up 250 ms or `Ctrl+Alt+A`).
4. Resume, then repeat next-slide. Expect exactly one advance.

### 7. Unknown window configuration

1. Create a configuration the classifier cannot identify confidently, for
   example an unpaired presenter console or a PowerPoint window with an
   unexpected class/title.
2. Expect `UNKNOWN`, fail-closed rejection, and a diagnostic record listing
   process, class, title, foreground status, and monitor bounds.
3. Confirm no input reached PowerPoint.

### 8. PowerPoint closure

1. During a normal slideshow, close PowerPoint completely.
2. Expect `ADAPTER_UNAVAILABLE` and a transition to `ERROR`.
3. Confirm no input was sent and no retry loop occurs.

### 9. UIPI / elevation mismatch

1. Start PowerPoint **as administrator** and AirCue **non-elevated**.
2. Attempt navigation, pointer, click, double-click, and scroll.
3. Expect `INPUT_BLOCKED` and a transition to `ERROR`; no partial input.

## Result table

Copy this block once per PowerPoint version.

| # | Scenario | Observed target kind | Command | Expected | Observed | Pass/Fail | Notes / exact error text |
|---|---|---|---|---|---|---|---|
| 1 | Normal, single | | next | one advance | | | |
| 1 | Normal, single | | previous | one back | | | |
| 1 | Normal, single | | pointer | cursor on monitor | | | |
| 1 | Normal, single | | click | one click | | | |
| 1 | Normal, single | | double-click | one double-click | | | |
| 1 | Normal, single | | scroll | wheel only | | | |
| 2 | Normal, extended | | pointer corners | clamped, no fallback | | | |
| 3 | Presenter View | | next / previous | accepted | | | |
| 3 | Presenter View | | pointer/click/scroll | rejected, no input | | | |
| 4 | Ambiguous monitors | | any | UNKNOWN, no input | | | |
| 5 | Edit mode | | activation/gestures | rejected, no input | | | |
| 6 | Focus change | | any | PAUSED, no dispatch | | | |
| 7 | Unknown config | | any | UNKNOWN, no input | | | |
| 8 | PowerPoint closed | | any | ADAPTER_UNAVAILABLE / ERROR | | | |
| 9 | UIPI mismatch | | any input | INPUT_BLOCKED / ERROR | | | |

## What to paste back

- The per-version header block.
- The completed result table.
- The `aircue diagnose` output for each distinct target kind.
- The exact rejection detail for every failed or unexpected case.

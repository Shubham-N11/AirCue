# Manual validation kit

These checks need a camera and PowerPoint, so they are not part of CI. Run them
from an interactive terminal in the repository with the app installed
(`pip install -e ".[dev]"`).

## Real-camera smoke test (task 7.7)

Record this header first:

| Field | Value |
|---|---|
| Date | |
| Tester | |
| Windows edition/build | |
| CPU / RAM | |
| Camera model | |
| Camera mode (requested -> actual, fallback) | |
| PowerPoint version/build | |
| Display layout | |

The negotiated camera mode is the `camera` record in
`%LOCALAPPDATA%\AirCue\logs\aircue.jsonl`: it reports `requested`, `actual`, and
`fallback`.

With a deck open and **Slide Show > From Beginning** running:

1. Run `aircue diagnose`. Expect `target=normal_slideshow` and the slideshow
   monitor bounds.
2. Run `aircue run`. Expect `aircue: ready (state=idle)`.
3. Activate with a thumbs-up held 0.8 s. Expect `ACTIVE`.
4. Show an open palm and rotate clockwise once. Expect exactly one slide
   advance. Hold the pose; expect no repeat.
5. Rotate counter-clockwise once. Expect exactly one slide back.
6. Show a fist. Expect `PAUSED` and no commands. Hold a thumbs-up 0.25 s.
   Expect `ACTIVE` again.
7. Pinch to enter pointer mode and move the hand. Expect the cursor on the
   slideshow monitor only; frame corners stay inside its bounds.
8. Pinch once. Expect exactly one left click after the double-click window.
9. Double-pinch. Expect exactly one double-click and no extra single click.
10. Scroll up and down. Expect wheel movement in the requested direction only.
11. Press `Ctrl+Alt+D`. Expect `IDLE` and no further input.
12. Press `Ctrl+Alt+Q`. Expect `EXITING`, an exit code of 0, and the camera
    released.
13. Start `aircue run` again. Expect a clean start, proving the camera was
    released.

Record Pass/Fail and notes per step, then paste the header, results, and any
unexpected log records back.

## Soak test (task 9.6)

Self-check the sampler once:

```powershell
python tests/manual/soak.py --self-check
```

Then:

1. Close other applications that may hold the camera and start a slideshow.
2. Run the soak harness (add `--config PATH` if not using the default config):

   ```powershell
   python tests/manual/soak.py --minutes 60
   ```

   The harness starts `aircue run`, samples memory, threads, and handles every
   5 s, and writes `reports/soak-*.csv` plus `reports/soak-*.md`.
3. Use AirCue normally for the hour: navigate, pause/resume, point, click,
   scroll, deactivate, and reactivate every few minutes.
4. At the "60 minutes reached" message, press `Ctrl+Alt+Q`.
5. Verify the summary reports exit code 0 and the AirCue process is gone.
6. Paste the summary and CSV into the hardware validation evidence.

Pass condition: clean exit, no unhandled crash, and flat memory, thread count,
and handle count across the samples (no sustained growth).

## PowerPoint compatibility matrix (task 5.9)

Follow `openspec/changes/establish-aircue-gesture-navigation/PPT-MATRIX.md` for
every installed PowerPoint version. Paste the per-version header, completed
result table, and `aircue diagnose` output back so the permanent document
(`docs/presentation-integration.md`, task 5.10) can be written from observed
evidence only.

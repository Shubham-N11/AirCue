# Release checklist (task 10.4)

## Owner decisions

- **License:** MIT, confirmed by Shubham-N11 on 2026-11-22. `LICENSE` and the
  `pyproject.toml` license field must stay in agreement.
- No license claim beyond MIT is made for bundled third-party models; the
  hand-landmark model is downloaded separately and its redistribution terms are
  still unverified.

## GitHub repository settings

Apply in the repository web UI; the local clone cannot change them.

- **Description:** Gesture-based PowerPoint control from a standard webcam
  (Windows).
- **Topics:** `aircue`, `computer-vision`, `mediapipe`, `powerpoint`,
  `gesture-recognition`, `windows`, `python`.
- **Default branch:** `main`.
- **Actions:** enabled. The `CI` workflow runs on pushes and pull requests.
- **Branch protection on `main`:** require the `windows` check to pass, block
  force pushes and branch deletion. Require a pull request once there is more
  than one contributor.
- **Issues:** enabled. Projects and wiki are optional.

## v0.1.0 release draft

- **Title:** AirCue v0.1.0.
- **Tag:** `v0.1.0` from `main` only after the acceptance report (task 10.5)
  exists.
- **Notes:** summarize only verified capabilities, link the README and the
  validation reports, and list unverified hardware/performance items explicitly.
- **Assets:** source archive only. Do not attach the hand-landmark model until
  its redistribution terms are confirmed.

## Final gates

1. Task 10.1 commands pass locally: `python -m pytest -q`,
   `python -m ruff check src tests`, `python -m mypy src`.
2. Task 10.2: `openspec validate establish-aircue-gesture-navigation --strict`.
3. Task 10.3: CI green on `main`.
4. Task 10.5: acceptance report maps every requirement to evidence.
5. Task 10.6: working tree clean and the commit history is the verified tree.

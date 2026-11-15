# Contributing

AirCue targets Windows 10/11, 64-bit, Python 3.11+.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Required checks

Run these before every pull request:

```powershell
pytest
ruff check .
mypy
```

Tests must not require a camera or a running PowerPoint instance. Use synthetic
landmarks, fake frame sources, and fake presentation adapters. Manual checks are
recorded under `tests/manual/` or `docs/` with the hardware and software used.

## Scope and behavior

The OpenSpec change at `openspec/changes/establish-aircue-gesture-navigation/`
is the behavioral contract. Do not add gesture vocabulary, states, transitions,
or presentation commands without updating the relevant spec and design first.

Performance and reliability claims require recorded measurements. Do not
describe a proposed target as verified.

## Licensing

No license has been selected. Do not assume permission to reuse the code, and
do not add a license file or license claim without the owner's written decision.

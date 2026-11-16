# AirCue

AirCue turns a standard laptop webcam into a hands-free PowerPoint controller.
A small set of deliberate hand gestures drives slide navigation, pause/resume,
a pointer, clicking, and scrolling without touching the keyboard or mouse.

AirCue is under active development. The behavioral contract, architecture,
performance targets, and reliability requirements live in
[`openspec/changes/establish-aircue-gesture-navigation`](openspec/changes/establish-aircue-gesture-navigation).

## Status

Pre-release. No performance or hardware-compatibility claim is verified until it
is recorded in the project's validation reports.

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.11 or newer
- A standard webcam
- Microsoft PowerPoint (2019, 2021, or Microsoft 365) for presentation control

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run the checks:

```powershell
pytest
ruff check .
mypy
```

## Usage

Command-line usage is documented as the runtime is implemented. The status
overlay and keyboard shortcuts are the primary controls; the full gesture
reference will be added with the runtime.

## Documentation

- [Vision pipeline](docs/vision-pipeline.md)
- [Tracker selection](docs/tracker-selection.md)
- [Presentation integration](docs/presentation-integration.md) - planned

## License

No license has been selected for this project. Do not assume permission to
copy, modify, or distribute it; licensing is an explicit owner decision.

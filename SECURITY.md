# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately to the project owner. Do not open a
public issue for a vulnerability until the owner confirms disclosure timing.

## Scope and design

- AirCue processes camera frames locally. It does not upload frames or telemetry.
- Debug frame capture is opt-in and writes only to a configured local directory.
- The presentation adapter sends synthesized input only to a revalidated
  PowerPoint target and fails closed when the target is uncertain.
- No credentials or secrets are required at runtime.

## Supported versions

AirCue is pre-release. Security fixes are applied to the current development
branch only until a supported release line is published.

## Licensing

No license has been selected for this project. This policy does not grant any
right to use, copy, or redistribute the code.

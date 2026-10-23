## Purpose

Report the actual compatible Market Shadow artifact state without implying production influence or backdated information.

## ADDED Requirements

### Requirement: Canonical advisory status
The GUI SHALL resolve canonical Market Shadow sidecars before interpreting missing manifest status, reject incompatible artifacts and distinguish supported unavailable, not-run, running, completed, failed and stale states.

#### Scenario: Valid successful sidecar
- **WHEN** a selected projection has a compatible successful advisory sidecar without a manifest result section
- **THEN** the GUI shows completed advisory coverage and observation timing.

#### Scenario: Invalid or incompatible sidecar
- **WHEN** sidecar identity, time, content or production-influence checks fail
- **THEN** it is not reported as successfully available.

### Requirement: Advisory-only point-in-time identity
The GUI SHALL preserve both projection and market observation cutoffs and SHALL keep Market Shadow production influence false.

#### Scenario: Later advisory observation
- **WHEN** a valid market snapshot was observed after the projection cutoff
- **THEN** it is labelled as later advisory information and cannot silently reinterpret the original report.

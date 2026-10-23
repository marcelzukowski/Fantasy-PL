## Purpose

Preserve useful manual selections while preventing incompatible or corrupted evaluations from appearing current.

## ADDED Requirements

### Requirement: Compatible evaluated scenarios
The desktop SHALL reuse an evaluated manual result only when its canonical context, full native input identity, selected transfer identities and internally consistent result payload are valid.

#### Scenario: Fresh compatible result
- **WHEN** an unchanged valid saved result matches the current verified inputs
- **THEN** it remains available with its unchanged objective.

#### Scenario: Stale or damaged result
- **WHEN** context, input, path totals or required result fields differ or are missing
- **THEN** the desktop does not display an evaluated objective and explains that re-evaluation is required.

### Requirement: Non-destructive recovery
The desktop SHALL preserve valid stored transfer selections when their result is unusable and SHALL allow explicit re-evaluation under current legality without modifying production Decision reports.

#### Scenario: Reconstruct stale selections
- **WHEN** a user loads stale selections into a valid current context
- **THEN** current canonical validation determines evaluation eligibility and the old score is not reused.

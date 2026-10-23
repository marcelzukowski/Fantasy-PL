## Purpose
Let managers construct and compare saved manual simultaneous transfer packages using verified
existing projections and the native strategic objective without changing production recommendations.

## ADDED Requirements

### Requirement: Accessible manual scenario editor
The desktop SHALL offer Transfer Comparator with independent OUT/IN selections K0..5, incoming
name/position/club/price filters, final squad, bank/FT/hits and a one-action HOLD reset. All player
names SHALL remain fully readable and validation errors SHALL disable evaluation.

#### Scenario: Atomic package editing
- **WHEN** a user selects a complete legal package whose intermediate prefixes are illegal
- **THEN** the final simultaneous package is accepted without imposing transfer order.

#### Scenario: Visible OUT selection
- **WHEN** a user clicks an owned player's checkbox or row
- **THEN** its OUT state toggles visibly, checked rows are distinguished, a 0/5 through 5/5 counter updates, and a sixth selection is rejected with a clear message.
- **AND** mismatched OUT/IN counts are explained immediately, stale previews/results are cleared and evaluation stays disabled until canonical validation passes; deselection, saved selection reload and Reset to HOLD update the same controls.

#### Scenario: Twin OUT and IN comparison tables
- **WHEN** a user selects or deselects either side using its checkbox, row or Space key
- **THEN** the same checked-row styling and independent 0/5..5/5 counter apply, filters/sorting preserve hidden choices and complete packages use unchanged canonical validation.

### Requirement: Local analytical player views
The desktop SHALL display twin OUT/IN tables and a finance side panel in adjustable roughly 30/48/22 proportions, with scenario results underneath. Both tables SHALL filter locally by name, position, club, price and selected-only state and sort by name, price, points so far, next-GW projection and five-GW total. IN SHALL default to descending five-GW total, with an ascending/descending control. OUT SHALL preserve owned order by default.

#### Scenario: Available five-GW metadata
- **WHEN** a verified compatible V22 context is loaded
- **THEN** IN shows season points, next-GW xP, five-GW xP total and all fixtures in those five GWs with available per-fixture xP using existing verified local data, without provider calls or projection generation.
- **AND** an identified single-fixture GW may supply that fixture's xP; multi-fixture GW totals SHALL NOT be divided or duplicated as fixture estimates. Missing data SHALL remain unknown, five-GW totals require complete coverage and available GW totals remain inspectable.
- **AND** these display metrics SHALL NOT change the existing three-GW V3 objective, FT valuation or report schemas.

### Requirement: Canonical legality and objective
Scenarios MUST use canonical prices, squad/club/position/duplicate/bank/FT/hit rules and native
3-GW V3 scoring with future K<=2. The UI SHALL disclose bounded-search approximation.

#### Scenario: FT4 and FT5 fifth transfer
- **WHEN** K5 is legal with FT4 or FT5
- **THEN** the hit is respectively4 or0, and HOLD at FT5 never accumulates a sixth FT.

### Requirement: Compatible baselines and comparison
The comparator SHALL show complete objective, deltas versus current HOLD and independent
production V3, current XI/captain/vice and future sequence only for matching verified contexts.
Manual winners SHALL NOT become automatic production recommendations.

#### Scenario: Context changes
- **WHEN** projections, ownership, prices, FT or GW change
- **THEN** old results become stale and cannot contribute comparable objective numbers.

### Requirement: Responsive external evaluation
Heavy evaluation SHALL run only in the external scientific worker, with progress, cancellation,
timeouts and explicit pending/evaluated/failed states. Duplicate scenarios SHALL reuse verified
context-specific results. GUI SHALL require no solver environment or scientific stack imports.

#### Scenario: Cancellation and shutdown
- **WHEN** the user cancels evaluation or closes the app
- **THEN** evaluation stops, incomplete results are discarded and no worker remains orphaned.

### Requirement: Local scenario persistence
Users SHALL save, rename, reload and delete named scenarios locally, preserving canonical IDs,
context and necessary metadata. Explicit reconstruction against a new context SHALL revalidate
current legality and SHALL NOT silently reuse old results or alter existing production reports.

#### Scenario: Reload stale scenario
- **WHEN** a saved scenario is loaded under new account/projection context
- **THEN** transfers are restored for editing, stale scores are unavailable and new evaluation is required.

### Requirement: Safe verified Windows release
The lightweight ONEFILE SHALL pass focused tests and packaged comparator workflow smoke before
root promotion. V22, stable production V3, Chip/Market Shadow separation and read-only account
behavior SHALL remain unchanged; no startup provider calls or diagnostic production imports.

#### Scenario: Failed acceptance
- **WHEN** build or packaged workflow acceptance fails
- **THEN** preserve the stable root executable and report the concrete blocker.

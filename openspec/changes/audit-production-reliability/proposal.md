# Proposal

## Why

The completed audit reproduced inconsistent saved Comparator results, stuck worker startup states and successful Market Shadow sidecars displayed as unavailable. Correct these reliability boundaries without changing engine mathematics.

## What Changes

- Validate saved result content and current evaluation identity; preserve selections for explicit re-evaluation.
- Recover failed worker startup/initialization with finite progress and actionable logs/retry.
- Resolve compatible canonical Market Shadow sidecars with truthful state and observation timestamps.
- Add failing regressions before fixes, focused integration tests and a lightweight Windows release after smoke validation.

## Capabilities

### New Capabilities

- `desktop-result-integrity`: trustworthy local Comparator persistence and compatible evaluation reuse.
- `desktop-worker-lifecycle`: recoverable scientific worker startup and terminal states.
- `market-advisory-status`: truthful canonical advisory artifact status and timing in the GUI.

### Modified Capabilities

None. Existing `v3-stable-planner` requirements remain unchanged.

## Impact

Desktop store/widget, MainWindow process handling, projection discovery/trust display and focused tests. No new dependencies, engine scoring/search, V22/model parameters, Chip mathematics, FT rules, external solver integration or historical data changes. User explicitly authorizes implementation, quality gates and conditional EXE build/promotion; never close their running root EXE forcibly. The search universe remains native V3 K<=2; manual fixed current K0..5 remains unchanged.

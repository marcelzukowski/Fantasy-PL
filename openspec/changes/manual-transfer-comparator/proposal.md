# Proposal

## Why
Managers need to compare their own simultaneous K0..5 transfer packages with HOLD and stable
production V3. Automated K<=5 research remains NO-GO; manual evaluation is a separate product feature.

## What Changes
- Add a Transfer Comparator tab with search/position/club/price filters, exact final-squad validation,
  bank/FT/hits, saved named scenarios and side-by-side complete-objective/lineup/path comparison.
- Run native fixed-current-package V3 in a persistent external scientific worker, with context caches,
  progress, cancellation, timeout and stale-result rejection. No automatic evaluation or account writes.
- Package and smoke-test the lightweight ONEFILE; promote only after all requested acceptance checks.

## Capabilities
### New Capabilities
- `manual-transfer-comparator`: construct, persist and compare user-selected legal transfer scenarios.
### Modified Capabilities
None. Production V3 recommendation generation, scoring and future K<=2 remain unchanged.

## Impact
New desktop widgets, local persistence and external-worker modules; small MainWindow integration.
No solver dependency, diagnostic production imports, V22 refresh, Chip Screen or report rewrites.

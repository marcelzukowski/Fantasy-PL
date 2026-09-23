# Persisted planning report schemas

The desktop read/write boundary uses immutable dataclass schemas in
`fpl_engine.reports`:

- `decision_report_v2` (`DecisionReportV2`)
- `chip_report_v2` (`ChipReportV2`)
- `analysis_manifest_v2` (`AnalysisManifestV2`)

Every new Decision and Chip report embeds the canonical `PlanningContext` from
P0.1/P0.2. Its `context_id` is the only semantic identity for a planning run.
An Analysis manifest embeds the same immutable context deliberately: it lets
history loading prove its identity without reconstructing mutable account state.

## Dispatch and compatibility

Readers inspect `schema_version` before parsing. A declared version other than
the current version fails closed with `Unsupported report schema version.`
Reports with no declared schema are read through a conservative legacy adapter.
A legacy report without a verifiable `PlanningContext` remains
`LEGACY / UNVERIFIED`; it stays discoverable but cannot become active analysis.
Adapters never invent a context ID, report hash, V3 value, or preview identity.

## Integrity

A `ChipReportV2` records the SHA-256 of the exact Decision-report bytes it
consumed. `AnalysisManifestV2` references Decision and optional Chip reports by
project-relative path and SHA-256. Loading a verified analysis rechecks both
reference hashes, the shared context ID, and read-only mutation lists before Qt
receives a view model.

## Preview identity

Each `StrategyPreview` has both a strategy slot (`short_term`, `balanced`,
`long_term`, or `strategic`) and an order-independent `plan_id` derived from
its OUT/IN transfer set. Short and Balanced may therefore intentionally share a
plan ID while remaining separate strategy slots. UI card ordering is never part
of preview identity.

## Adding a schema version

Add a new explicit schema constant and parser, keep the old parser as a
read-only migration adapter if its semantics remain unambiguous, add a
round-trip and unknown-version test, and do not change the canonical
`PlanningContext` identity scheme.

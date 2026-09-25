# Legacy optimizer performance contract

The legacy V1 transfer search has an exhaustive reference implementation,
`legacy_reference_search`, which is retained exclusively for bounded differential
tests and benchmarks. Production V1 uses `optimized_search`. It first rejects
only candidates that cannot form a valid regular transfer under the existing
rules: position replacement, owned IDs, duplicate IDs within a multi-transfer, missing projections, bank,
and the per-club maximum. Source-pool duplicate rows are deliberately not
collapsed because historic V1 could expose duplicate equal plans for malformed
input; normal production pools remain unique. `validate_squad` remains the final canonical legality
authority for every survivor.

Both paths construct the same `TransferPlan` fields and apply the historic sort
key exactly:

```python
(-plan.net_gain, plan.transfers_out, plan.transfers_in)
```

Consequently a tie remains deterministic and HOLD retains its historic position
when no transfer has a greater net gain. The production path does not change
transfer limits, hit cost, selling-price calculation, free-transfer banking,
formation, captaincy, or recommendation data contracts.

V1 and V2 can receive the run-scoped `DecisionInput.lineup_for` provider. Its
cache is keyed by context, target Gameweek, complete squad IDs, rule version,
and chip lineup options. It is never global or shared between incompatible runs.
Search diagnostics are written only to machine-readable shadow-run provenance;
they are not a normal Analysis UI output.

# Shared DecisionInput and run-scoped caches

`DecisionInput` is the engine-only owner of one verified `PlanningContext` during a
single desktop decision execution. It contains the validated `SquadState`, raw
canonical player pool, canonical projection mapping and `(player_id, GW)` lookup,
rules, freshness records, pipeline provenance, artifact identities, and a bounded
run-local cache. It has no Qt objects, display formatting, report view state, or
mutable account data.

The desktop decision runner builds it once after `PlanningContext` and production
bundle verification. The existing shadow runner receives that same object for
Greedy, Optimizer V1 and Optimizer V2. V3 and current strategy previews consume
the same state/pool/projection objects. Standalone `shadow` CLI use preserves its
previous loader for compatibility.

The cache lifetime is one `DecisionInput`; it cannot cross a process, analysis,
GW, bundle, FPL material-state change, or `context_id`. Its lineup key is:

```text
(context_id, target_gameweek, sorted_15_player_ids, optimizer_rule_version,
 triple_captain, bench_boost)
```

Projection lookup and candidate-universe indexes are built once per input. The
cache records construction, lookup/universe, policy and lineup hit/miss timings
for diagnostics; it does not alter result serialization or normal UI text.

V3 retains its existing internal per-plan/per-GW lineup cache. It evaluates
future-GW transformed projection rows and beam states, while the shared cache
owns current-GW preview evaluation; combining them would create duplicate or
ambiguous cache ownership. Chip-specific simulation state remains separate;
shared PlanningContext/projection integrity stays its boundary.

Policy-local candidate ranking, V1/V2 searches, V3 beam expansion, price signals,
chip simulation, historical report loading, and GUI rendering deliberately remain
separate because their semantics are not identical shared preparation work.

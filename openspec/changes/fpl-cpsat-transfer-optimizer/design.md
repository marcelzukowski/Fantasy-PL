# Phase1: exact final packages with a linear surrogate

## Isolation and universe
The normal scientific `.venv` adapter reads canonical SquadState, PlayerProjection and OptimizerRules.
Only a JSON-stdio `.venv-solver` subprocess imports OR-Tools. Production and dependency environments
remain unchanged. Retain all owned15 and all eligible incoming players with finite existing
ev_next_3 signals and valid native metadata/prices. No heuristic shortlist; record excluded
IDs, full sorted universe and input digest. Frozen GW8 lineage is verified before generation.

## Mathematical model
For each unique player p, Boolean x_p means inclusion in the FINAL roster. Independently for each
K0..5 enforce sum(x)=configured15, position totals=configured quotas, per-club totals<=configured3,
sum(1-x) over owned=K, sum(x) over incoming=K. Bank is initial bank plus personal sale proceeds of
outgoing owned players minus current buying prices of incoming players, and must be nonnegative.
Integer prices use0.1m. No intermediate-prefix constraints; atomic funding and club rotations remain legal.

## Surrogate and limits of proof
Maximize sum(weight_p*x_p) - native hit(K,FT)*1,000,000. Weights are existing ev_next_3
rounded half-even to1e-6 points. This sums ALL15 roster signals: no XI, captaincy, bench realization,
future actions or terminal FT. It is NOT complete V3. Native terminal FT and HOLD tolerance stay untouched.
Per-objective rounding error<=15/(2*scale)=0.0000075 points; a difference may have twice that error.
Reject nonfinite or unsafe integer coefficients. Only the exact scaled surrogate has an optimality claim.

For each K return up to five candidates independently. After final roster S add sum(x_p for p in S)<=14.
Use sorted IDs, fixed seed42, one worker, no randomized search, zero relative/absolute gap limits and
default1s per solve (GW8:2s). Bound total worker execution by6*5*limit plus process overhead.
Later-rank OPTIMAL applies to the remaining universe after no-good exclusions, not the original optimum.
FEASIBLE is unproven; UNKNOWN, INFEASIBLE and MODEL_INVALID fabricate no candidates. Report status,
objective, maximizing upper bound, wall and deterministic time per attempt. Time-limited feasible prefixes
can vary with wall-clock load; verify deterministic repeated controlled and GW8 results explicitly.

## Native acceptance and tests first
Tests are written before implementation. Every returned package is reconstructed by native
StrategicPlannerV3._make_action with a diagnostic K5 configuration, or canonical HOLD accounting.
Native validate_squad checks final roster, positions and club caps. Compare sorted OUT/IN/result IDs,
bank, hits, FT transition and recomputed scaled surrogate. Any mismatch raises; no silent approximation.
Use existing atomic/funding/K5 fixtures and small exact native enumeration plus Hypothesis. Include
HOLD/K1/K2, FT4/5, bank, club caps, insufficient pools, input validation and honest solver statuses.

## GW8 and excluded work
Use the verified existing V22 bundle and matching account context, with no provider refresh. Report
per-K counts, top packages, status/bound, native legality, bank/hits, runtime/memory and known K2/K3
membership. If absent, diagnose eligibility, constraints and surrogate rank without injecting references.
No V3 path scoring, multi-GW solver, production integration, new projections, Chip Screen or EXE build.
Those are Phase2 or later and require new authorization. Do not automatically archive the change.

## Phase2 authorized diagnostic design
Leave Phase1 files unchanged. A diagnostic subclass overrides only current-GW action generation
to return one natively validated K0..5 package, then delegates to the unchanged native `_search`.
Future actions retain default K<=2, beam40 and horizon3. Replay native actions, optimized XI, hits,
FT and terminal value independently. Path points already include hits: do not subtract twice.
Exact returned-path accounting does not establish globally optimal multi-GW planning.

Use caches owned by one immutable input digest plus PlanningContext ID/config. Full state keys
include ordered player metadata, prices, bank, FT, GW and timestamp. Cache native future actions,
action evaluations, per-GW projection views and completed root searches. Never reuse caches across
inputs; independent production incumbent runs without challenger caches. Validate paths before
promotion into the completed-package cache. Failed/incomplete work cannot replace the incumbent.

First A, then B/C: total GW8 budget900s, at most80 unique candidate evaluations; per-model CP1s.
Deadline checks between native action operations cancel incomplete paths. Record PARTIAL on budget
exhaustion. Timings separate generation, native validation, V3 evaluation, replay and total wall time;
track cache hits and parent/worker peak memory. Frozen reference paths are independently replayed
and are never injected into candidate generation.

C's additions use full-roster Hamming distance >=min(4,2*K) from every prior roster and
different OUT and IN sets from every prior package. For K0 no additional distinct HOLD exists.
The constraints can exhaust a restricted universe before five additions; record the status rather
than relaxing cuts or injecting reference actions. Parent-side native validation also verifies cuts.

## Phase2B bounded neighborhoods
Reuse only integrity-checked Phase2 paths whose context, complete input digest, configuration,
candidate artifact hashes and native source/rule identities match. Independently replay all cached
unique paths and the incumbent; never recompute the expensive Phase2 search. Pick up to3 strongest
K2 anchors with incoming-set diversity, retaining their verified complete V3 objectives.

Each CP neighborhood preserves anchor IN, at least one anchor OUT, and targets exact K3/K4/K5.
Cells cover extensions retaining all OUT and additional incoming position GK/DEF/MID/FWD. Enforce
final-roster legality only, allowing atomic funding/club cycles. Bound proposals to72, single worker,
seed42,0.35s/solve, with exact no-good deduplication. No GW8 names/IDs or reference packages enter
generation, cheap ranking or slot allocation.

Use the native optimized-XI path applying a proposal then HOLD/HOLD as a cheap, exact path-value
lower bound for ranking; label it separately from full future-search evaluation. Prefer strong
anchors, top native lower bounds and structural diversity, allocating up to4 slots/K (12 total).
Keep valid Phase2 packages separate and do not spend new-search slots on duplicates. Future V3 is
unchanged K<=2/horizon3/beam40. A120s monotonic deadline includes all new full-search/replay work;
incomplete evaluations are discarded and reported PARTIAL, preserving all valid earlier results.

Synthetic reduced oracles enumerate legal current actions and exhaustively compare their native
fixed-root future K<=2 evaluations. Report retained/missed optimum, objective gap and reason for
atomic K4, FT5, constrained funds, strong K2 with superior K3, disconnected K3 and HOLD dominance.
No claim of global multi-GW optimality; no iterative tuning after the bounded evidence is collected.

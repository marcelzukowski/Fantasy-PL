# Optimization and objective fidelity

## Stable production scope

Stable V3 currently searches at most K<=2 transfers per action/gameweek and uses a beam. It is an approximate search and is not globally optimal. Final path selection compares the complete objective for unrestricted search and forced HOLD; exact ties and absolute differences within `1e-9` select HOLD. Preserve the separate alternative path and comparison semantics in reports.

State and objective accounting must respect legal squads, personal sale prices, bank, free transfers, hits, availability, horizon, chips, lineup/captaincy value and terminal free-transfer value. Do not change search coverage, scoring, pruning or valuation as an incidental UI or report edit.

## Claims and experiments

A claim of optimality requires the explicit mathematical model, solver status and exact search scope (including candidate restrictions, K limits, beam/pruning and horizon). Distinguish measured outcomes on named contexts, mathematical guarantees proved for the stated scope, approximations and heuristic rankings, and assumptions or validation not yet tested.

The K<=5 guarded portfolio is NO-GO: a reduced exhaustive adversarial oracle found exact `290.372` versus `282.101`, a gap of `8.271`. Keep expanded search diagnostic-only until a new task defines the model, scope, acceptance and validation. Do not restart heuristic search by default.

CP-SAT Phase1 is a separately authorized diagnostic generator: its scaled linear all15 `ev_next_3`
surrogate minus hits is not the complete V3 objective. OPTIMAL applies only to its declared candidate
universe, exact K and no-good exclusions. See [Phase1 evidence](../cpsat-phase1.md); no Phase2 evaluation
or production integration follows automatically from surrogate optimality.

The final [Phase2B anchored-neighborhood experiment](../cpsat-phase2b.md) is NO-GO: known GW8
K3 remains outside the bounded surrogate winners, and reduced atomic/disconnected cases miss by
88,71 and0.4 complete-objective points. Legal atomic packages can have no legal K2 anchor; retaining
anchor incoming sets can exclude a better K3. Preserve those limits rather than claiming general
coverage from a successful native replay. No further heuristic cycle or production integration is implicit.

## Stable production dependencies

Use verified V22 projections. Market Shadow must have no production influence (`false`). Experimental challengers, scratch results and their objective comparisons do not alter production recommendations unless explicitly integrated and reviewed.

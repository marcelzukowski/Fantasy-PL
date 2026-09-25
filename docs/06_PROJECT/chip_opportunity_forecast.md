# Chip Opportunity Forecast V1

`Chip Opportunity Forecast V1` is a read-only, run-scoped advisory artifact. It
uses a verified `PlanningContext` and its frozen `DecisionInput`; it never fetches
providers, changes an FPL account, changes V22 projections, or changes the V3
objective, beam search, transfer recommendation, or exact Chip Screen result.

## Horizon and chip availability

The forecast uses the canonical existing six-gameweek chip horizon. It stops at
the active chip-period boundary. Availability is evaluated separately for every
target Gameweek using the existing chip-state rules, so a first-half chip cannot
be proposed in the second half and the independent second-half Wildcard is not
advanced into the first half.

## Methods

- **Triple Captain** compares the existing normal and triple-captain lineup
  semantics for the current squad and records the candidate captain.
- **Bench Boost** compares the existing normal and bench-boost lineup semantics
  for the current squad. It is labelled `STATIC_SQUAD_APPROXIMATION`: it does not
  claim to optimise a future squad.
- **Free Hit** first applies a deterministic, cheap static-pool screen. The score
  is the available non-owned ceiling minus the owned-player floor for the target
  Gameweek. Only the strongest Gameweek at or above the documented threshold of
  `1.0` receives one existing exact Optimizer Free Hit evaluation. Other screened
  rows have no invented exact EV.
- **Wildcard** is diagnostic only. It records static-squad replacement pressure
  as `LOW`, `MEDIUM`, or `HIGH`; it has no simulated value and cannot recommend a
  transfer.

Missing owned-player coverage remains missing. It produces a `PARTIAL` or
`UNAVAILABLE` advisory state instead of being converted to zero.

## Confidence and provenance

Each row stores target-GW coverage, the existing projection confidence, a small
horizon-distance adjustment, method, assumptions and source context. The artifact
stores schema/version, `context_id`, prediction timestamp, projection run,
generation timestamp, coverage, warnings, source metadata, and a
`production_influence: false` marker.

It is written immutably to:

```text
data/processed/chip_opportunity_forecasts/<projection_run_id>/chip_forecast_<sha>.json
```

The decision report contains a typed path/hash reference. Replay Archive V1
records and revalidates that exact artifact. A forecast failure is advisory-only:
a valid decision remains valid and a replay archive failure cannot fail it.

## Relationship to existing chip evaluation

The forecast is a near-term outlook, not a replacement for the exact Chip Screen.
It uses no provider calls and does not rerun simulations. The exact screen
continues to own its established horizon, strategic scan, and recommendation
semantics. V3 accepts the forecast structurally for future work but deliberately
does not read it when scoring paths.

Performance metadata records total runtime, cumulative runtime per chip type, the
number of exact Free Hit evaluations, screened-out Gameweeks, and cache hits. A
cached result only returns for the identical context, horizon, chip-state
signature, configuration version, and Free Hit threshold.

`realised_incremental_ev` and `timing_regret` are explicitly present as `null`
in V1. They are archival hooks for a later historical chip-policy evaluation;
V1 neither invents realised outcomes nor regenerates a forecast during replay.

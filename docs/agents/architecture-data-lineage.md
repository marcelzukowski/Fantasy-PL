# Architecture and data lineage

## Boundaries

- `src/`: prediction and decision engine.
- `desktop_app/`: FPL Control Center, state, data access, account sync and orchestration.
- `scripts/`: explicit maintenance, acquisition and diagnostic entry points.
- `tests/`: regression, contract and oracle coverage.
- `data/`: processed inputs and user/runtime state. `scratch/`: experiments, diagnostics and run evidence.

Inspect the live modules and callers before changing an interface. Keep diagnostic prototypes out of production imports. The production simulator is `fixture_simulator_v22_lineup_coherent_logit` (V22); verify run metadata and input lineage instead of selecting the newest artifact.

## Data lineage

Important runs should identify season, gameweek, seed, simulation count, simulator, source artifacts and output path. Decision-time evidence must respect its recorded planning cutoff; later observations may be retained but are ineligible for older contexts. A scratch artifact is not production evidence without a verified production contract.

The external Decision worker archives standalone pre-deadline results without requiring Chip. The offline prospective evaluator locks one primary archive per season/GW and scores only verified frozen forecasts and eligible saved V3/HOLD counterfactuals. See [prospective validation](../prospective-validation.md) for commands, capture failures, cohort definitions and the 6–10 GW protocol; never regenerate forecasts to fill evaluation gaps.

## Desktop contracts

`DesktopSquadState` represents 15 unique legal players, personal account prices, bank, free transfers and chips. `player_id` is canonical; `provider_id` maps external FPL element IDs. Account-derived entry ID and purchase/selling prices must survive GUI save/edit flows. New players must not receive invented personal prices.

The FPL integration is read-only. The production GUI must not execute transfers, chip use, captaincy, squad confirmation, or other account mutations. See [production safety and release](production-safety-release.md).

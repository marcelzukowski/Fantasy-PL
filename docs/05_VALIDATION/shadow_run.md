# Current-season shadow run

Run a non-mutating experimental recommendation with a complete local account
state and point-in-time production projections:

```powershell
.venv\Scripts\python.exe -m fpl_engine shadow --squad-state data\local\squad-state.json
```

The JSON must contain `prediction_timestamp`, `season`, `current_gameweek`,
`players`, `candidate_pool`, `bank`, `free_transfers`, `chip_state`, `pipeline`
and `projections`. `players` contains exactly 15 explicit `SquadPlayer` records:
`player_id`, `position`, `club_id`, `purchase_price`, `current_price`, and an
optional explicit `selling_price`. The command never guesses purchase prices,
bank, free transfers or chips.

`projections` contains serialized `PlayerProjection` records made by the
existing Team Strength → Minutes/Talent/Event → FixtureSimulator →
ProjectionBuilder pipeline at the exact `prediction_timestamp`. The command
requires `pipeline.simulations_per_fixture: 10000`; it refuses a diagnostic
simulation count. `data_freshness` should identify each materialized source,
its known/snapshot time and RawStore receipt. Missing provenance appears as a
warning; a future known or snapshot timestamp fails the run.

The reports are written under `data/processed/shadow/<season>/`. They are
labelled `EXPERIMENTAL / SHADOW MODE` and `NOT PRODUCTION PROMOTED`. They never
call an authenticated FPL endpoint, submit transfers, or mutate FPL state.

For a generated current candidate pool and projections, use the composed command:

```powershell
.venv\Scripts\python.exe -m fpl_engine predict-current --season 2026/27 --gameweek <GW> --squad-state data\local\squad-state.json
```

The equivalent two-step form passes the generated bundle explicitly:

```powershell
.venv\Scripts\python.exe -m fpl_engine shadow --squad-state data\local\squad-state.json --prediction-bundle data\processed\predictions\2026-27\<timestamp>\shadow_projection_bundle.json
```

The public FPL team endpoint does not provide every required account-state
field. In particular, bank, free transfers, purchase/selling prices, and
authoritative chip state cannot all be reconstructed safely, so the local
squad-state input remains required.

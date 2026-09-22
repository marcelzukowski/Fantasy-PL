# Current-season prediction pipeline

The `predict-current` command implements roadmap tasks `PIPE-001` through
`PIPE-006`. It composes the existing provider, canonical-data, feature, model,
simulation, scoring, projection, and shadow contracts. It never submits an FPL
action.

## Run it

From the repository root, a production-size projection run is:

```powershell
.venv\Scripts\python.exe -m fpl_engine predict-current --season 2026/27 --gameweek <GW>
```

To produce the projection artifacts and an immediate shadow recommendation:

```powershell
.venv\Scripts\python.exe -m fpl_engine predict-current --season 2026/27 --gameweek <GW> --squad-state data\local\squad-state.json
```

The squad-state file must provide exactly 15 players and explicit purchase and
current prices, bank, free transfers, chip state, current Gameweek, season, and
the same prediction timestamp as the run. The generated current bundle supplies
the candidate pool and projections.

`--simulation-count` is a diagnostic override. The default remains 10,000 per
fixture. Any other value is labelled `NON-PRODUCTION DIAGNOSTIC` in the run and
shadow reports. `--prediction-timestamp` accepts an aware ISO-8601 timestamp.
When omitted, the command freezes the current UTC time immediately after source
materialization, so every recorded retrieval is available by the prediction
cutoff. If an explicit timestamp predates a fetched record, point-in-time
validation rejects the run.

## Data and temporal policy

Official FPL `bootstrap-static`, the current fixture schedule, current prices,
and a season-specific scoring and optimizer rule configuration are required.
Prior `event-live`, versioned STRICT historical context, API-Football injuries,
local snapshots, and manual temporal context are optional only where the V1
models already define a prior or unknown-state fallback.

Network access remains in the existing provider adapters. Successful bytes pass
through `HttpCache` and `RawStore`; a cache hit makes no network request and no
new raw snapshot. Current source states are also stored idempotently in
`fact_fpl_snapshot`. Every record is checked against one `PredictionContext`.
FPL snapshot evidence must satisfy `source_snapshot_timestamp <
prediction_timestamp`; other facts use `known_at <= prediction_timestamp`.
`known_at`, `retrieved_at`, and source snapshot time remain separate fields, and
future-dated provenance fails the run.

Fixture identity is based on competition, season, and canonical home/away team
identity. Kickoff time and Gameweek remain mutable fixture attributes, so known
reschedules retain the fixture ID. Each fixture is simulated separately, which
preserves DGWs; absent Gameweeks remain explicit BGWs in `PlayerProjection`.

The public team endpoint cannot reconstruct bank, free transfers, purchase and
selling prices, and authoritative chip state. `--team-id` therefore fails with
the missing account fields and directs the user to `--squad-state`; it never
infers them.

## Outputs

Each run writes a timestamped directory under
`data/processed/predictions/<season>/<timestamp>/`. It contains:

- prediction context, source provenance, and freshness;
- canonical identity audit and canonical Parquet exports;
- current players and the six-Gameweek fixture horizon;
- Team Strength, Minutes, Tactical Context, Talent, and Event outputs;
- DuckDB/Parquet and JSON `PlayerProjection` output;
- the generated optimizer candidate pool and shadow projection bundle;
- warnings, configuration hashes, deterministic seeds, versions, and artifact
  hashes in `run_manifest.json`;
- `current_report.md`, plus machine and human shadow reports when squad state is
  supplied.

Missing required sources, explicit season rules, prices, critical identities,
or complete horizon timestamps fail clearly. Optional unsupported context stays
unknown and is listed in warnings; it is never converted to an observed zero.

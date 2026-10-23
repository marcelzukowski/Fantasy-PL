# Prospective workflow verification example

The final example is [verified/report.md](verified/report.md), with [machine-readable evidence](verified/report.json). The shared [primary ledger](primary.jsonl) fixes exactly one immutable archived analysis for GW6 and GW7. This is historical demonstration data, not a prospective study; the registered study starts with GW9.

Reproduction from the project root, using existing local public data only:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -m fpl_engine.validation.prospective `
  --season '2026/27' --gw-min 6 --gw-max 7 `
  --ledger docs/audits/prospective-validation-example-2026-10/primary.jsonl `
  --output data/processed/prospective_validation/example-reproduction
```

Use a new output directory for changed evidence. Retain the ledger. Local snapshot read permissions are necessary; unreadable files are explicitly excluded, so inspect coverage before interpreting a report.

Verified cohort: 667 distinct players, 667 observations per GW, 1,334 rows. V22 points MAE 1.0981315592, RMSE 2.0603646399; minutes MAE 14.6687775862. Baseline and subset denominators are reported explicitly. In the saved transfer-candidate subset, the recent historical mean outperforms V22 descriptively; the example is not selected to make every model metric favourable.

Saved historical V3 and frozen HOLD are scored from their own contemporaneous full lineups, ordered bench, observed outcomes, captain/vice and hits using the existing exact autosub evaluator. GW6 scores 51 versus 41; GW7 scores 81 versus 83. This is a no-chip current-GW counterfactual, not a sequential account backtest or a retrospective run of the corrected current planner.

The earlier root-level `report.json`/`report.md` are retained development output. Their scoring was already based on canonical autosubs, but their explanatory sentence incorrectly described DNP scoring as unsupported. The verified version corrects that description and the `autosub_status` field name without rewriting the earlier output or any frozen forecast. Numerical scores are unchanged.

Focused checks: 60 Decision/capture/replay tests passed; 22 new capture/evaluator checks passed (overlapping capture tests); the raw developer gate passed 33 tests. New-module Ruff correctness, additional E4/E7/F checks and formatting pass. Tests cover the real PlanningContext interface, archive tampering and lock conflicts, raw checksum/completion guards, missing-history handling, duplicate/mixed identities, saved lineups, canonical autosubs and captain fallback. The GUI's missing-bundle test now selects an explicit sentinel bundle so it exercises its mocked error path independently of live Run Center contents.

The protection check compared 2,793 previously recorded source/input hashes outside three intentional existing-file edits: worker capture hook, the test isolation adjustment and the architecture guide. No unexpected change was found. Root/dist EXEs remain 78,869,641 bytes each, SHA-256 `4befb95fcdbf71e84abb7af3a5100dcfd51d8f96907b848036ef5a3d46f56ff1`. No production model/V3 scoring/search modification, provider request, training, projection, Chip Screen or build was run.

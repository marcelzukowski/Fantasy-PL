# Replay Archive V1

Replay Archive V1 preserves an immutable, pre-deadline half of every eligible analysis under:

```text
data/processed/historical_replay_cases/<season>/GW<NN>/<archive_case_id>/archive_case.json
```

The archive case references canonical bundle, projection manifest, DecisionReport and AnalysisManifest by
project-relative path and SHA-256. It copies no large projection payloads: the source run already has a
required-artifact hash manifest and validation rechecks those exact bytes. This is typically a few KB per
analysis run; at 2–5 runs/GW it is roughly 0.2–1 MB/season excluding later outcome rows. Reproducibility
wins over this storage saving because references are rehashed before use.

A case is created after a valid analysis manifest is persisted. It needs a verified PlanningContext, matching
DecisionReport, zero external mutations, an official deadline, and prediction/analysis/decision timestamps
strictly before that deadline. A case may be written later to preserve an already proven historical run.
Invalid or legacy reports are never upgraded by guessing.

`archive_case.json` is immutable. Repeating the same archive request is idempotent. A different immutable
payload with the same identity fails loudly. Optional Chip data is deliberately not part of the core case;
it can remain a separately referenced report without delaying a transfer-policy archive.

Market Shadow is referenced only when an already local, hash-verified snapshot belongs to the projection run,
is PIT-valid, and declares `production_influence: false`. Otherwise it is `UNAVAILABLE`. Price signals are
`AVAILABLE`, `STALE`, or `UNAVAILABLE`; the present V3 contract does not persist an exact signal snapshot,
so no reference is inferred.

Outcomes live only in `outcomes/<outcome_id>.json` beside the archive. `ReplayOutcomeV1` contains post-event
points, minutes, fixture IDs and optional post-GW prices. It is never merged into the pre-deadline archive or
passed to policy execution.

Developer commands:

```powershell
python -m fpl_engine.validation.replay_archive list --season 2026-27
python -m fpl_engine.validation.replay_archive validate --season 2026-27
python -m fpl_engine.validation.replay_archive status --gw 6
python -m fpl_engine.validation.replay_archive create --analysis <analysis-manifest.json>
python -m fpl_engine.validation.replay_archive outcomes --archive <archive_case.json> --source <local-outcomes.json>
```

`PRE_DEADLINE_COMPLETE` means all frozen inputs validate. `OUTCOME_COMPLETE` means an outcome companion is
present. `REPLAY_READY` additionally requires archived historical price evidence, which is necessary for
sequential replay. `INVALID` is fail-closed.

Optimizer V1 currently persists ranked alternatives without an unambiguous selected primary action. New
reports should add an explicit V1 selected-action field only if the live V1 contract proves it; archive and
replay intentionally leave V1 strict evaluation unavailable until then.

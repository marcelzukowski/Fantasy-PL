# Point-in-time player minutes history (P2.2)

`PlayerMinutesHistorySnapshot` is an immutable, advisory companion to a planning context. It contains only completed, source-proven player/fixture appearances whose kickoff is before the planning cutoff and whose finished outcome was available in a timestamped local source no later than that cutoff. A gameweek number is metadata: fixture ID plus actual kickoff chronology is the identity rule, so doubles remain two rows and blanks create no invented zero-minute row.

The preferred acquisition path is a locally retained Official FPL element-summary response paired with a locally retained finished-fixture response. Exact source bytes remain in the existing RawStore/HttpCache lifecycle; the normalizer records the immutable raw snapshot ID and observed/outcome-known timestamp. Desktop startup and report loading never issue per-player history requests; the explicit Run new analysis workflow may capture an advisory pre-deadline snapshot in its external Decision worker. An explicit developer refresh may supply `player_minutes_history_records.json` beside a canonical projection bundle; otherwise a deterministic `UNAVAILABLE` companion snapshot is saved and no missing value becomes a fact.

Snapshots are stored at `data/processed/player_minutes_history_snapshots/<projection_run_id>/` and are referenced, with a SHA-256, from the typed Decision report and Replay Archive. Replay loads that exact artifact; it never rebuilds historical minute evidence from later outcomes. Derived sequences and variability are diagnostic-only advisory inputs for Player Availability Risk. They do not alter V22, projected minutes/points, transfer policies, captaincy, chips, or Market Shadow.
## Official FPL acquisition (P2.3)

Run this only as an explicit data refresh; desktop startup, tabs, report loading and replay never call it:

```powershell
.venv\Scripts\python.exe -m fpl_engine refresh-player-history `
  --season 2026/27 --gameweek 6 `
  --squad-state data/user/squad_state.json `
  --prediction-bundle data/processed/predictions/2026-27/<run>/shadow_projection_bundle.json `
  --decision-report data/processed/desktop_decisions/2026-27/<report>.json
```

The command reuses `OfficialFPLAdapter`, its five-minute configurable `HttpCache` TTL and the canonical `RawStore`. Official FPL's `element-summary/<player_id>/` endpoint is per player; one completed-fixture schedule request is joined by fixture ID. It requests the deduplicated squad, decision/preview/captain candidates and up to ten existing top targets. The immutable acquisition receipt is saved beside the bundle as `player_minutes_history_records_<hash>.json`; each entry carries the raw receipt ID, checksum, cache key, observed timestamp and cache status.

The command is phase A without a decision report and phase B when the saved report is supplied. It never reruns a decision. A player/fixture is accepted only when the receipt was observed by the PlanningContext cutoff and the paired official fixture says it finished. A refresh after a deadline is retained for a future decision but is rejected for that old decision/replay. Per-player failure remains an advisory `PARTIAL`/`UNAVAILABLE` condition.

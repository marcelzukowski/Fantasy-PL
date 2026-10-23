# Prospective V22 and V3 validation

Prepared 23 October 2026. This is an offline evidence workflow, not a model improvement or optimizer experiment. The [historical validation](audits/v22-predictive-validation-2026-10.md) remains a two-GW retrospective evaluation, with verdict **PARTIALLY VALIDATED**.

## Capture readiness

**Before this change: FAIL for a standalone Decision → prospective evaluation workflow.** A normal saved full analysis already called `write_analysis_run` → `archive_analysis`, but only after Chip completed, failed or was cancelled. The standalone Decision button persisted a DecisionReport without automatically creating an archive. A separate strict post-GW scorecard with deterministic cohorts, matched baselines and an incremental primary-selection ledger was also missing.

**After this change: PASS, subject to explicit per-run validation.** The external Decision worker now calls `capture_decision` after its existing report is finalized. This creates a separate minimal PARTIAL AnalysisManifestV2 and reuses the existing replay archive writer. PARTIAL means no Chip report; it does not mean a newly invented incomplete prediction. Missing deadlines, invalid artifacts or late completion are reported as `PROSPECTIVE_CAPTURE=UNAVAILABLE`; a successful Decision remains available. Successful capture prints `PROSPECTIVE_ARCHIVE=<path>` in the worker log. No Chip, provider or model is invoked by capture.

| Required evidence | Existing preservation / treatment |
|---|---|
| Verified V22 bundle and exact prediction time | Projection manifest, bundle hashes and PlanningContext |
| Official deadline, GW and season | PlanningContext plus independently checked local official bootstrap evidence |
| Player points, minutes and distributions | Frozen `shadow_projection_bundle.json`, referenced by hash |
| Full V3 recommendation | `policy_results.strategic_v3`: current action, selected path, alternative path, complete objective and diagnostics |
| Selected XI, bench, captain and vice | Saved V3 path steps and the strategic preview |
| HOLD counterfactual | Existing `hold_now_counterfactual.path[0]`, including its own zero-transfer squad, XI, bench and captain |
| State and configuration identities | Context fingerprint, projection/config manifest hashes, rule/model versions and V3 diagnostics; new captures additionally hash the worker, V3 source and optimizer source at capture time |
| Baseline history | Existing local official raw snapshots; evaluator requires checksums, pre-prediction retrieval and pre-prediction completion evidence |

HOLD here means **no transfer in the evaluated current GW**. Its later V3 path may transfer in future weeks; it is not an all-HOLD multi-week policy. The evaluator uses the saved current-GW counterfactual, never a transferred XI relabelled HOLD. Older generic policy replay's 15-player squad totals and HOLD-lineup fallback are not used as realised XI policy scores.

New capture manifests live under `data/processed/prospective_captures/<season>/`, outside GUI Run Center history because they do not contain a display-state snapshot. Replay cases use the existing `data/processed/historical_replay_cases/<season>/GWxx/<case>/archive_case.json` tree. Existing reports and snapshots are not upgraded, rewritten or backfilled. Files must be retained: references and hashes detect deletion or alteration, but are not an independent backup.

Reused functionality: `PlanningContext`, `AnalysisManifestV2`, projection artifact verification, `build_archive_case`/`write_archive_case`, archive discovery/parsing/validation, raw public snapshot metadata and the exact autosub evaluator. Existing `attach_outcome` accepts manually supplied canonical outcome rows, but does not itself establish official completion, matching baseline cohorts or a longitudinal scorecard. The new command reads existing raw outcomes directly and writes separate reports, avoiding changes to historical archives or redundant outcome copies.

## Routine workflow

Before each deadline, use the normal standalone **Decision Engine** action with the explicitly selected, approved production V22 projection bundle and current compatible account state. This task does not generate that bundle. Complete the Decision with time to spare and check the successful archive marker; if capture is unavailable, resolve the named problem before the deadline. Merely opening an old report does not create eligible evidence. Capture refuses retrospective creation after the deadline.

After the GW finishes, the normal separately authorized public-data acquisition workflow must have saved official bootstrap and event-live snapshots. Completion requires both `finished` and `data_checked`. The evaluator itself never downloads missing outcomes, refreshes predictions, reruns a planner, syncs the account or submits account changes. Missing final outcomes are reported as pending/unavailable.

From the repository root in PowerShell, run after each completed study GW, using a **new output directory** and the **same ledger**:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -m fpl_engine.validation.prospective `
  --season '2026/27' --gw-min 9 --gw-max 18 `
  --ledger data/processed/prospective_validation/2026-27/primary.jsonl `
  --output data/processed/prospective_validation/2026-27/after-GW09
```

For the next update change only the output name, for example `after-GW10`. Each report accumulates the completed eligible GWs in the declared range. Existing identical outputs are idempotent; conflicting outputs are refused. Never discard the shared ledger to choose a more favourable archive. Concurrent use of the ledger is rejected. A stale lock requires checking that no evaluation process remains before manually removing that lock; the tool does not break locks automatically.

The command returns JSON and Markdown scorecards with input identities, included primary archives, exclusions, cohort counts, matched baselines and separate decision availability. A readable empty report is not evidence of a successful quality evaluation: check included GW/player counts and exclusion reasons. There are no silent zero imputations.

## Selection, leakage and immutable evidence

- One primary archive per season/GW: latest eligible prediction timestamp; archive creation time and path deterministically break ties. Require an archive physically recorded, according to its local creation timestamp, before the official deadline, matching projection/report hashes, read-only compatible context and canonical V22 identity. Diagnostic and copied bundles outside the canonical tree are ineligible.
- At first evaluation, the chosen archive hash and context are appended to the shared ledger. Later reports retain that choice, even if another archived run appears. Changed or missing locked evidence fails rather than falling back to a different run. Multiple analyses and seed replicates never inflate the GW count.
- Official source payload checksums and season/GW/deadline identity are checked. Outcomes must be explicit and final; earlier in-play snapshots are not made final by a later completion flag. Identity joins use official element IDs and stable codes where available, not names.
- Previous-GW and recent-mean baselines use only completed historical GWs observed by the original prediction timestamp. The minutes-aware reference scales historical points per minute by saved predicted minutes and is unavailable at zero historical minutes. Each comparison uses identical available player-GW rows on both sides and reports its denominator.
- The recent mean uses up to three available completed GW observations. New players may have fewer; contributing GW IDs and history counts are recorded per row, so a one- or two-observation mean is not silently presented as three independent observations.
- Immutable output directories retain prior reports. Corrections or newly available outcomes produce a new dated report, with changed source hashes visible; they never rewrite a forecast or its old scorecard. Keep both reports when official results are corrected.
- Local timestamps and hashes provide operational provenance, not externally notarized proof against deliberate coordinated tampering. Retain backups and freeze configuration changes as separate study phases.

## Predeclared 6–10 GW protocol

Registration is after the GW8 deadline of 23 October 2026, 17:30 UTC. **The prospective primary study starts at GW9.** GW6–7 are historical examples; GW8 may later be a separately labelled bridging observation, not retroactively registered prospective evidence.

1. Primary review after the first six scheduled study GWs, **GW9–14**; extend the same frozen protocol to **GW18** for ten scheduled GWs. Record missing/invalid GWs rather than replacing them with a favourable run. If fewer than six are scoreable, report insufficient coverage and continue only with an explicitly documented extension.
2. Keep the V22 configuration, production V3 K≤2, terminal FT valuation, HOLD tie correction and Market Shadow influence=false fixed. Record legitimate software/configuration changes by identity and report separate phases. Do not tune on the weekly scorecard or select configurations by realised results.
3. Forecast primary endpoints: player points MAE/RMSE/bias versus previous available GW and recent three-GW mean on matching rows; minutes MAE/RMSE/bias. Secondary: minutes-aware reference, tied-rank Spearman within each GW, points-threshold Brier scores and calibration descriptions.
4. Always show all available players and pre-outcome decision-relevant cohorts: predicted starters (expected minutes≥60), high projection (xP≥2), saved transfer-candidate IDs, saved captain-candidate IDs, positions and predicted-minutes buckets. Their exact definitions are recorded by the evaluator. These subsets overlap; do not sum them. Separate inactive-player prevalence from performance among realistic candidates.
5. Decision endpoint: saved production V3 current-GW XI+captain points minus its frozen hit cost, versus its own saved HOLD current-GW counterfactual, on the same context and outcomes. Report both scores and the paired difference only when both are valid. No transfer-policy advantage follows merely from lower forecast MAE.
6. Score saved lineups with the existing exact autosub evaluator, using observed points and deterministic appearance indicators from actual minutes. Use the saved vice-captain only when the captain did not appear; subtract the saved hit cost. This does not rerun lineup selection or optimize with hindsight. Missing outcomes/positions, inconsistent previews, unsupported chips and absent counterfactuals remain explicit unavailable observations, not zero gains or losses. The endpoint is a no-chip, single-decision counterfactual, not a sequential realised account backtest.
7. Review weekly descriptive results for data problems; make the six-GW and ten-GW reviews even if results are unfavourable. Report total scheduled GWs, valid distinct GWs, missing rows, decision coverage and phase identities. Provide per-GW errors and paired baseline differences, not just one pooled number dominated by inactive players.
8. Six to ten GW clusters do not support precise season-wide superiority claims. No IID player-row confidence interval or significance claim is permitted. Repeated players and shared fixture/team outcomes remain dependent. A later, larger scorecard may justify GW-block inference; 20 GWs is only a planning threshold, not a guarantee of adequate power.

## Verification and release scope

The example uses only existing archived GW6–7 forecasts and local official outcomes. No new Decision, projection, provider request, account action or Chip computation is part of generating it. Its historical policy versions remain historical; no corrected current V3 result is substituted into an old report.

Use the [verified example report](audits/prospective-validation-example-2026-10/verified/report.md) and its [verification notes](audits/prospective-validation-example-2026-10/README.md). It reproduces 1,334 observations and V22 MAE 1.0981. In the 22 saved transfer-candidate observations, V22 MAE is 3.0577 versus 2.6364 for the recent mean: lower population-wide error does not imply improvement on every decision cohort. Saved historical V3 versus its own current-GW HOLD scores are +10 points in GW6 and -2 in GW7; these two observations do not establish current-policy superiority.

An **EXE rebuild is not necessary**: the only runtime hook is in `desktop_app.decision_runner`, launched in the external project `.venv` by the unchanged GUI command. The evaluator and capture helper are source-side validation tools; no GUI, spec, styles or packaged imports changed. Existing root/dist EXEs remain in place.

Remaining operational requirements: run Decision before deadline; retain referenced artifacts and ledger; acquire final public outcomes through the normal explicit workflow; inspect capture/evaluation availability. Chip effects, realised terminal FT value and sequential future actions remain outside this endpoint. Actual test and historical-example results are recorded alongside the delivered example.

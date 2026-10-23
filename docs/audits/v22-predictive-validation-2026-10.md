# V22 predictive quality validation — October 2026

Evaluation date: **23 October 2026**. Verdict: **PARTIALLY VALIDATED** for the two frozen forecast cohorts below. Durable predictive superiority and realised superiority of the current decision policy remain **insufficiently evidenced**.

V22 has lower descriptive points errors than the specified simple baselines in GW6–7. This is a genuine frozen-forecast/outcome join, extending the [comprehensive audit](fpl-comprehensive-audit-2026-10.md), which had not established one. It is not a representative season backtest. Two gameweeks, many inactive players, weak evidence at the top of the ranking, and historical policy differences prevent a stronger conclusion. The [reliability fixes](../production-reliability-fixes.md) improve software trust; their passing tests establish no predictive advantage.

Only this report and its [supporting diagnostics](v22-predictive-validation-2026-10/) were created. No production changes, projections, training, provider calls, policy experiments, Chip Screen or EXE build were performed.

## 1. Number and validity of historical snapshots

The bounded inventory searched local `data/` and `scratch/`, without following junctions, symlinks or test/dependency directories. It found **108 manifests**: 36 V22 occurrences, 70 V1, one V2 and one V21. Occurrences include copies and experiments, not independent forecasts. There were 109 projection bundles; one canonical bundle, `20260915T123625Z`, has no manifest and cannot establish a verified V22 identity.

Of 14 canonical V22 runs, **three distinct bundles have matching pre-deadline archive references and intact artifact manifests**: GW6 `20261009T063838Z`, GW7 `20261012T091744Z`, and GW8 `20261022T071806Z`. **Two are scoreable**; local final outcomes stop at GW7. Nine archive cases reference those three bundles. All nine pass the existing `validate_archive_case` checks, including report hashes, schema, PlanningContext compatibility, deadline and projection integrity. Nine reports do not create nine forecast samples.

The primary eligibility rule was fixed before inspecting forecast errors: canonical V22, matching manifest artifact hashes, official local deadline observed by prediction time, prediction strictly before that deadline, a pre-deadline archive reference to the exact bundle hash, and final local outcomes. If multiple eligible forecasts exist for a GW, select the latest eligible prediction timestamp. Here there is only one scoreable eligible bundle per GW. This deliberately conservative rule excludes self-declared timestamps unsupported by an archived byte identity. It does not assert that other runs were generated late.

| GW | Frozen prediction timestamp UTC | Official deadline UTC | Simulations | Bundle SHA-256 |
|---|---|---|---:|---|
| 6 | 2026-10-09 06:38:38.729897 | 2026-10-10 10:00 | 20,000 | `bde8b0437c75b722262d6ddc0ee263a21fb190ab879db296f104a3b19d09be64` |
| 7 | 2026-10-12 09:17:44.347023 | 2026-10-17 10:00 | 20,000 | `d145a3ba9d1e5f4436dd63d7d7e64dc0cce7d6787ffb026b958ea43d131c0210` |

Both have 18 manifest artifact references with no mismatches. Both identify simulator `fixture_simulator_v22_lineup_coherent_logit`. Their mode field says `NON-PRODUCTION DIAGNOSTIC`: the historical writer labels counts other than exactly 10,000 this way. Their canonical location and verified operational Decision archives establish their use here, rather than assuming that this label alone approves or rejects production. These measurements apply to these 20k operational bundles, not automatically to every configuration or today's dirty source tree.

Official deadlines were independently read from hash-verified local bootstrap payloads retrieved no later than each prediction. The archive and context deadline agree. This is local operational provenance, **not an externally notarized timestamp or proof against deliberate rewriting of all local evidence**.

## 2. Covered gameweeks, outcomes and identities

Primary cohort: **season 2026/27, GW6 and GW7, 667 unique players, 667 rows per GW, 1,334 player-GW observations**. Each player appears twice. All target rows have exactly one fixture; no DGW or BGW is represented.

Local public-API evidence contains 53 bootstrap, 323 event-live and 292 element-summary metadata/payload pairs. All **668 payload checksums match** their recorded SHA-256. Latest bootstrap completion flags establish `finished=true` and `data_checked=true` for GW1–7. The latest locally retrieved event-live payload for each completed GW supplies explicit actual points and minutes. These later outcome observations are used only as labels, never as prediction inputs or baseline history at an earlier cutoff.

Joins use canonical `player_id` → snapshot `provider_id` → official event-live element ID. Every primary player also has the same stable official player `code` in the later bootstrap identity table. No names, fuzzy matches or missing-to-zero conversion are used. There are **zero missing-identity or missing-outcome exclusions within the primary cohort**. A separate element-summary history cross-check agrees on points, minutes, goals and assists for **73 available primary observations**, with zero disagreements; this corroborates only that subset.

**715/1,334 rows (53.6%) explicitly have zero minutes and zero points.** These are genuine observed zeros, but their prevalence makes population-wide error and ranking substantially easier than choosing between realistic transfer targets. Outcomes cover only the roster published at prediction time, not later additions outside that forecast universe.

## 3. Exclusions and their reasons

Full occurrence-level paths, exact timestamps, deadlines, bundle hashes and overlapping exclusion reasons are in [results.json](v22-predictive-validation-2026-10/results.json). Inventory records are in [inventory.json](v22-predictive-validation-2026-10/inventory.json). **34 of 36 V22 manifest occurrences are excluded from primary metrics**; exclusions overlap and should not be summed by reason.

| Canonical run | GW | Primary treatment |
|---|---:|---|
| `20260915T130524Z` | 5 | No pre-deadline archive reference to exact bundle hash |
| `20260915T194106Z` | 5 | Same |
| `20260916T204815Z` | 5 | Same |
| `20260917T120819Z` | 5 | Same |
| `20260917T182728Z` | 5 | Same |
| `20260918T101242Z` | 5 | Same |
| `20260921T200047Z` | 5 | Also post-deadline: GW5 deadline was 18 September 17:30 UTC |
| `20260921T204826Z` | 6 | No pre-deadline archive reference to exact bundle hash |
| `20261009T063838Z` | 6 | Included |
| `20261010T081128Z` | 6 | No pre-deadline archive reference to exact bundle hash |
| `20261010T091918Z` | 6 | Same; later timestamp alone does not establish archived existence |
| `20261012T091744Z` | 7 | Included |
| `20261022T071806Z` | 8 | Verified archived forecast; final GW8 outcomes unavailable |
| `20261023T170248Z` | 8 | No qualifying archive reference and no final GW8 outcomes |

The other 22 V22 occurrences are excluded as follows:

- Ten `data/interim/desktop_chip_strategy/...` materializations: future/diagnostic contexts, not canonical weekly forecasts; nine target future GW11–14 and one targets GW5.
- Five `data/diagnostics/...` benchmark runs: four fixture-parallel 25-simulation configurations and one 100-simulation strategic benchmark, all targeting GW12.
- Six scratch GW4 replay/ensemble runs: `captain068g/integrated_replay/v22_real`, `captain068h/ensemble_mean`, `captain068h/seed_202627`, `seed_606`, `seed_91991`, and `captain068j/default_v22`. They are reconstructed or seed experiments, not demonstrated historical forecasts. The ensemble additionally fails the manifest hash for `player_projections.json`; it is not repaired or scored.
- One packaged-root copy of the archived GW8 run: duplicate evidence, not another sample; outcomes also pending.

The 72 non-V22 manifests and the unmanifested bundle are outside the verified V22 cohort. Historical V1 walk-forward output is not relabelled V22. There are no player-row exclusions after primary snapshot selection. For the minutes-aware baseline only, 581 rows lack positive summed historical minutes and are excluded from **both sides of that matched comparison**.

## 4. V22 points accuracy

Errors use `prediction − actual`; negative bias means underprediction. MAE is mean absolute error, RMSE is the square root of mean squared error. Units are FPL points per player-GW. All results are descriptive.

| Cohort | N | MAE | RMSE | Bias |
|---|---:|---:|---:|---:|
| All | 1,334 | 1.0981 | 2.0604 | -0.1565 |
| GW6 | 667 | 1.1015 | 2.1100 | -0.1747 |
| GW7 | 667 | 1.0948 | 2.0095 | -0.1383 |
| GK | 146 | 0.7248 | 1.3497 | +0.2146 |
| DEF | 434 | 1.1954 | 2.0808 | -0.1823 |
| MID | 596 | 1.1302 | 2.1245 | -0.1617 |
| FWD | 158 | 1.0550 | 2.2890 | -0.4091 |

| Predicted points | N | MAE | RMSE | Bias |
|---|---:|---:|---:|---:|
| [0, 2) | 952 | 0.6522 | 1.5777 | -0.1244 |
| [2, 4) | 373 | 2.1786 | 2.8982 | -0.2046 |
| [4, 6) | 9 | 3.4817 | 4.2193 | -1.5580 |
| [6, 8), [8, infinity) | 0 | Unavailable | Unavailable | Unavailable |

For players who actually appeared, N=619, MAE=1.9423, RMSE=2.9313 and bias=-0.7616. For those who did not appear, N=715, MAE=0.3673 and bias=+0.3673. These outcome-conditioned descriptions help diagnose the aggregate; they are not prospective selection rules.

**No confidence intervals or significance claims are supplied.** There are only two GW clusters, repeated players, shared team/fixture shocks and historical configuration-selection uncertainty. Resampling 1,334 rows independently would manufacture precision. These results neither establish an untouched holdout nor support season-level inferential claims.

## 5. Fair baseline comparisons

Baselines use only hash-verified event-live snapshots retrieved by prediction time and previous GWs whose completion was already observed in pre-cutoff official bootstrap data. GW6 uses GW3–5 for the recent baseline; GW7 uses GW4–6. Missing player observations are not invented.

- Previous available GW: latest earlier observed points.
- Recent mean: arithmetic mean of the latest three observed GWs, including explicit zero appearances.
- Minutes-aware: sum of points / sum of minutes over that history, multiplied by V22 predicted minutes; undefined if summed minutes are zero. This deliberately simple ratio can be unstable for tiny exposure and shares V22 minutes, so it is not a fully independent competitor.
- Zero forecast: a prevalence sanity check, not a useful team-selection policy.

| Same-cohort comparison | N | V22 MAE / RMSE | Baseline MAE / RMSE | Baseline bias |
|---|---:|---:|---:|---:|
| Previous GW | 1,334 | 1.0981 / 2.0604 | 1.3516 / 2.7490 | -0.0112 |
| Recent three-GW mean | 1,334 | 1.0981 / 2.0604 | 1.2420 / 2.3298 | +0.0356 |
| Minutes-aware | 753 | 1.7563 / 2.6856 | 2.4698 / 4.0628 | +0.5201 |
| Zero | 1,334 | 1.0981 / 2.0604 | 1.3643 / 2.7825 | -1.3373 |

For the **same 382 rows with forecast xP≥2**, V22 MAE/RMSE=2.2093/2.9362. Previous GW scores 2.9634/4.0733, recent mean 2.6571/3.4486, and minutes-aware 2.5171/3.3240. Thus the descriptive advantage is not solely caused by inactive players. This cohort is defined by V22 itself and is not a neutral independent target universe. No baseline tuning or superiority test was performed. Full matched metrics and row-level baseline values are retained in the supporting JSON.

## 6. Minutes prediction analysis

Minutes are the saved simulated expected minutes, not retrospectively substituted actual minutes. Aggregate MAE=**14.6688**, RMSE=**22.2000**, bias=**-0.4491 minutes**. GW6: 14.8920/22.3196/-0.8056; GW7: 14.4456/22.0797/-0.0925 (MAE/RMSE/bias).

| Predicted minutes | N | Points MAE | Minutes MAE / RMSE | Mean predicted / actual minutes |
|---|---:|---:|---:|---:|
| [0, 1) | 359 | 0.0641 | 0.9471 / 6.3096 | 0.000 / 0.947 |
| [1, 30) | 462 | 0.7500 | 15.8793 / 22.0613 | 13.495 / 10.944 |
| [30, 60) | 198 | 1.8981 | 31.0709 / 34.2326 | 45.820 / 47.141 |
| [60, 80) | 273 | 2.3410 | 19.6535 / 25.8844 | 72.875 / 75.886 |
| [80, 90] | 42 | 1.9164 | 8.9161 / 8.9419 | 81.095 / 89.524 |

Small global bias conceals large errors in the uncertain 30–60-minute group and conservative estimates for near-90-minute players. The 198 rows with absolute minutes error≥30 have points MAE=2.2406. This is an association, not a causal decomposition of points error. Start/appearance probability calibration, sparse-history strata and injury-conditioned accuracy were not established by this audit. The previous 29,563-row minutes-component validation remains useful component evidence, not an independent V22 points scorecard.

## 7. Ranking, captaincy and decision usefulness

Spearman uses average ranks for ties. The existing generic replay helper breaks ties by order, so this diagnostic computes tied ranks directly without changing production code.

| GW | Spearman, all 667 | Spearman within forecast top 20 | Actual mean points of forecast top 20 |
|---|---:|---:|---:|
| 6 | 0.7031 | 0.0458 | 3.20 |
| 7 | 0.6895 | 0.4327 | 5.25 |

Across the xP≥2 cohort, descriptive Spearman=0.1827. Much of the broad ranking separates inactive players from plausible starters; it does not demonstrate reliable ordering among close transfer targets. Top-20 rankings are especially unstable with two weeks.

Contemporaneous squad, Decision and preview evidence exists for these GWs. The latest eligible archived Decision per GW was inspected **without rerunning its policy**. Its main recommendation identifies `optimizer_v1`, even though separate historical `strategic_v3` results and a strategic preview also exist. These are not rewritten or presented as today's corrected V3.

| GW | Saved recommended captain | Saved xP | Actual points | Previous-GW captain baseline | Recent-mean captain baseline |
|---|---|---:|---:|---|---|
| 6 | E. Le Fée | 4.8512 | 2 | Groß: 6 actual | Groß: 6 actual |
| 7 | Haaland | 4.5935 | 13 | De Cuyper: 6 actual | Groß: 5 actual |

Captain baselines choose the highest baseline score **within that same recorded starting XI**, with canonical-ID tie-breaking. This isolates captain choice conditional on the historical XI; it is not an independently constructed baseline squad. Values are ordinary player points; both captains appeared, so doubling does not change the comparison. One week favours the baselines, one the saved recommendation. Two captain choices cannot establish captaincy superiority.

Saved transfer examples: GW6 Palmer→Mbeumo has forecast raw player gain +1.34335 and realised raw gain 0; GW7 Calafiori→Van Hecke has forecast +0.60355 and realised -2. These are **player-point differences**, not hit-adjusted XI/autosub/policy returns. The saved recommendation margins between alternatives are only 0.0847 and 0.0828. They illustrate narrow forecast distinctions, but do not measure sensitivity of current V3: changing its inputs or rerunning it was outside scope. Current V3 HOLD correction, terminal FT value, multi-GW outcomes, prices, hits and path-dependent future choices cannot be validated by these two one-GW comparisons. No sequential or current-V3 backtest is claimed.

## 8. Probability calibration

Threshold probabilities come from the frozen GW points distributions. Brier score is mean squared probability error; lower is better. All rows below use the same 1,334 observed player-GWs.

| Event | Brier |
|---|---:|
| Points≥5 | 0.07887 |
| Points≥8 | 0.03886 |
| Points≥10 | 0.01588 |
| Points≥15 | 0.00226 |
| At least one goal or assist (`p_return`) | 0.06487 |
| No goal or assist (`p_blank`) | 0.06487 |

The stored `p_return` means **goal or assist**, and `p_blank` its complement, as defined by `FixtureSimulator._summarize`. They do not mean points>2 and points≤2. The points-distribution helper also uses a blank label for a points threshold; conflating these meanings would give a false calibration result. All evaluated rows have one fixture, avoiding additional DGW aggregation interpretation.

For points≥5, probability-bin reliability is:

| Forecast bin | N | Mean forecast | Observed frequency |
|---|---:|---:|---:|
| [0, .10) | 913 | .01591 | .03286 |
| [.10, .25) | 298 | .17761 | .21812 |
| [.25, .50) | 123 | .28640 | .29268 |

No rows occupy ≥.50. Overall goal/assist-return probability averages .04924 versus observed .07871. This suggests underprediction in this sample; it is not proof of a stable calibration defect or a justified recalibration factor. Rare-event Brier scores benefit from many negatives; the very small ≥15 score does not establish useful haul forecasting. Full threshold reliability bins are retained in [supplement.json](v22-predictive-validation-2026-10/supplement.json). No calibrated-confidence or distributional-coverage claim is made.

## 9. Data leakage and integrity assessment

Confirmed safeguards: intact primary manifest hashes; matching official deadlines from pre-cutoff local bootstrap; exact bundle hashes in pre-deadline Decision archives; valid read-only PlanningContexts; canonical-ID and stable-code joins; baselines restricted to previously observed final GWs; later outcomes used only as labels. Ninety recorded source time fields across primary freshness/provenance files were checked, with no timestamp after the corresponding forecast. Market Shadow remains outside production influence in archive validation.

The current implementation checks frozen prior calibration cutoffs and source known-at times; the minutes feature builder rejects target-fixture and future information. These guards and metadata checks do not certify every historical training row, feature materialization, crosswalk or parameter-selection decision. No source re-execution or training-data audit was undertaken. Local timestamps can be edited; there is no independent append-only external timestamp proof.

The strict backtest script constructs V1, not V22. `captain068g/integrated_replay_r2.json` says `2026_27_outcomes_used=false`; its simulator-alignment results cannot substitute for realised accuracy. Replays, seed replicates, copied manifests and future Chip projections are excluded. Historical Decision reports retain their original policy version and meaning.

## 10. Most important observed errors and plausible sources

**Confirmed observations:**

- Minutes uncertainty is material: the 30–60 expected-minute group has minutes MAE 31.07. GW6 Henderson was forecast 21.72 minutes/0.765 points, actually 90/18; Cherif 13.12/0.508, actually 77/12. These cases combine an exposure miss with event returns; the full points discrepancy cannot be assigned to minutes alone.
- Large return errors also occur with reasonable exposure: GW6 De Cuyper 74.49 minutes/2.401 points versus 67/15; GW7 Neto 70.17/2.805 versus 90/15. Better minutes alone cannot explain these observations.
- Players who appeared are underpredicted by 0.762 points on average, while non-appearances receive positive expected points. High-xP bins and goal/assist frequencies also show descriptive underprediction.
- Forecast age at deadline is 27.36 hours for GW6 and **120.70 hours** for GW7. This is prediction age, not proof that every source was that old. There is no paired late-refresh forecast with the same verified eligibility to isolate freshness impact.

**Hypotheses requiring further evidence:** injury/news or rotation updates could explain some minutes misses; player event rates or bonus/defensive-return allocations could explain others. V22 enforces coherent lineups and inherits event/scoring machinery; structural consistency does not establish calibrated goals, assists, saves, clean sheets, bonus or defensive contributions. Opponent strength, home/away effects, fixture difficulty, sparse-history priors and injury subgroups are not causally identified here. There are no DGW/BGW observations. The audit does not retrain, retune or infer a specific component fix from two weeks.

## 11. Insufficient evidence and practical limits

No supported conclusion about season-level superiority, current-V3 realised decision superiority, fine differences between near-equal transfer targets, multi-GW forecast dependence, DGW/BGW behaviour, chip usefulness, injury calibration or stable top-captain ranking. The sample has two GW clusters, one season, one simulation count and no prospective pre-registered policy evaluation. Only nine player-GW forecasts reach xP≥4; none reach xP≥6.

The broad inventory is finite and local; it excludes junctions/dependency/test trees and is not a claim about unavailable backups or external storage. No old immutable report is reinterpreted as corrected V3. No new snapshot replaces an old one. Zero archive outcome companions was an archive-workflow gap, not absence of usable local raw outcomes; this audit joins raw evidence in its own directory instead of modifying those archives.

## 12. Three highest-value improvements, ranked

1. **Freeze a prospective matched scorecard using existing archive infrastructure.** Preserve a predeclared run-selection rule, all eligible players, source/config identities and simple baselines, then attach final outcomes after each GW. This is the prerequisite for deciding whether any model change adds value.
2. **Validate minutes, starts and availability on decision-relevant cohorts.** Stratify uncertain exposure, stable starters, sparse histories, injuries and forecast age; compare against frozen recent-minutes/starts baselines. Existing errors justify prioritising this investigation, not automatically changing a model.
3. **Evaluate return calibration and high-impact ranking separately from all-player MAE.** Track goals/assists, clean-sheet/defensive/bonus contributions, top-target ranking and squad-conditional captain baselines with sufficient weeks. Only then consider a separately scoped model improvement supported by out-of-sample gains.

These are recommendations for future work, not changes implemented by this task. No new heuristic, beam search or CP-SAT cycle is proposed.

## 13. Smallest prospective validation protocol

1. Before the next deadline, declare the operational V22 configuration and run-selection rule: last fully verified, explicitly approved operational run archived before deadline. A simulation-mode label alone is insufficient approval. Freeze one primary run per GW; retain other runs as secondary paired evidence, never additional independent GW samples.
2. Use existing `build_archive_case`/archive validation to preserve projection and manifest hashes, season/GW, official deadline/source, prediction and archive times, model/config identities, actual PlanningContext, saved decisions/captain/XI and account-state identity. Keep Market Shadow advisory and account access read-only. Store baseline input references and deterministic baseline outputs at that same cutoff. An optional second fixed refresh time must be declared in advance.
3. After the GW is officially finished and data checked, acquire outcomes through the normal separately authorised data workflow. Validate season, element IDs/stable codes and payload hashes; distinguish missing rows from explicit zeros. Use existing `attach_outcome` only in that future workflow. Preserve original snapshots and reports; later corrections receive a separately identified outcome version.
4. Compute next-GW points/minutes errors, position/xP/minutes strata, goals/assists and threshold reliability, ranking/top20, and same-XI captain baselines. Compare every baseline on the same cohort. Capture missingness and forecast age. Keep policy evaluation separate: saved actions, actual legal squad/prices/hits, captain fallback and autosubs, with a declared hold baseline and horizon. Never substitute hindsight lineups or an invented current-V3 replay.
5. Publish descriptive weekly results immediately. Target at least 20 distinct completed GW clusters before even attempting GW-block bootstrap uncertainty; 20 is a planning minimum, not a guarantee of power. Retain shared-fixture dependence within GW blocks, account for repeated-player dependence when pooling seasons, report leave-one-GW-out sensitivity, and continue collecting if intervals remain uninformative. Freeze metrics and change decisions before observing the evaluation outcomes; do not repeatedly tune on this scorecard.

This protocol reuses available archives and requires no capture feature implementation in this task. It does not require another projection now or an expensive Chip run.

## 14. Verdict, reproducibility and preservation

**PARTIALLY VALIDATED.** Two genuine, operationally archived pre-deadline V22 bundles can be joined to final local outcomes with verified identities and artifact integrity. Their descriptive points errors beat the specified baselines, including a decision-relevant xP≥2 subset. Minutes uncertainty, top-ranking instability and the small number of weeks remain material. Durable superiority and realised value of the current corrected V3 are **not established**.

Evidence files: [results](v22-predictive-validation-2026-10/results.json), [breakdowns and archive checks](v22-predictive-validation-2026-10/supplement.json), [frozen decision comparisons](v22-predictive-validation-2026-10/decision-metrics.json), [input SHA-256 ledger](v22-predictive-validation-2026-10/input-hashes.json), and [verification](v22-predictive-validation-2026-10/verification.json). Supporting scripts are read-only toward inputs and write only beside themselves. Reproduction uses existing `.venv`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUTF8=1`, and project root plus `src` on `PYTHONPATH`; run `evaluate.py`, `supplement.py`, then `decision_metrics.py`. Raw public snapshots may require the same filesystem read permissions used here. Do not rerun `inventory.py` to replace the original preservation baseline.

Arithmetic/tie/time self-checks, cohort uniqueness, probability bounds/order, nine archive validators and the 73-row history cross-check pass. **2,796 protected/input file hashes are unchanged**; same-permission Git status comparison shows no changes outside this audit. A privileged Git scan initially had different visibility into a pre-existing pytest temporary directory; comparison was repeated in the original permission context rather than treating its hidden entries as deletions. This limits claims about that unrelated temporary tree.

Root and dist EXEs are preserved, each **78,869,641 bytes**, SHA-256 `4befb95fcdbf71e84abb7af3a5100dcfd51d8f96907b848036ef5a3d46f56ff1`. No production test suite or GUI smoke was rerun because production and packaging were unchanged. The remaining validation blocker is insufficient independent gameweeks and prospective decision evidence, not a build failure.

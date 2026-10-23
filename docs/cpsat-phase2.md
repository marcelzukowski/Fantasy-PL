# CP-SAT Phase2 — frozen GW8 diagnostic evaluation

Completed the bounded experiment, without production integration. Evaluation and native replay
passed for all 128 strategy entries / 68 unique packages. **Promotion readiness: NO-GO.** Structural
diversity adds coverage, but neither B nor C improves the best complete objective over A, and all
three miss a known superior K3 package. This is a measured recall limitation, not an unfinished run.

## Scope and lineage

Frozen analysis: `desktop-analysis-20261022T081445787253Z.json`; verified V22 bundle
`20261022T071806Z`; context ID
`9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208`.
The input digest, configuration, candidate artifact hashes, every selected path, native replay and
worker status/bound are recorded in `scratch/cpsat_phase2_20261022/results.json` and adjacent files.
Historical analyses, account data, projections, dependencies and EXEs were not rewritten.

Phase1 files remain unchanged. Only `.venv-solver` imports OR-Tools9.15.6755; versioned JSON
contains context/input identity and configuration. The existing scientific `.venv` validates prices,
simultaneous legality, bank, FT and hits through native contracts. No competing FPL rules engine.

## Objective and unchanged search

The diagnostic adapter fixes the first action at K0..5 and calls native V3 `_search` once.
Future actions remain K<=2; horizon3, beam40, shortlist8/position, max24 actions/state,
lineup optimizer, captaincy and terminal FT heuristic remain unchanged. Price signals are unavailable
in this frozen comparison, matching the independently executed incumbent.

Reported complete objective is the sum of optimized XI points minus each GW's hits plus terminal
FT value. Native `projected_3gw_path_points` already includes hits. Every completed path is replayed
independently; an additional pass reconstructed all 68 unique paths from serialized JSON.
This is exact accounting of returned paths under bounded future search, **not globally optimal
multi-GW planning** and not CP-SAT optimization of the V3 objective.

## Candidate strategies and results

A: top5/K; B: top10/K; C: top5 plus up to5 structural alternatives/K. All use K0..5 and the
unchanged Phase1 all15 `ev_next_3` linear surrogate minus native hits at scale1e6. C additions must
have different OUT and IN sets from every earlier package and full-roster Hamming distance
>=min(4,2*K). No reference transfers are supplied to generation. Single worker, seed42, zero gap
limits and1s/solve. All 128 emitted solutions were OPTIMAL for their restricted surrogate models;
the three exhausted K0 attempts were INFEASIBLE. These statuses say nothing about V3 optimality.

| K | A count | B count | C count | Union unique | A complete V3 | B complete V3 | C complete V3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 1 | 1 | 1 | 147.42035 | 147.42035 | 147.42035 |
| 1 | 5 | 10 | 10 | 14 | 147.54340 | 147.54340 | 147.54340 |
| 2 | 5 | 10 | 10 | 12 | 148.26775 | 148.26775 | 148.26775 |
| 3 | 5 | 10 | 10 | 14 | 148.17525 | 148.17525 | 148.17525 |
| 4 | 5 | 10 | 10 | 13 | 147.60345 | 147.62200 | 147.62200 |
| 5 | 5 | 10 | 10 | 14 | 144.55305 | 144.55305 | 144.55305 |

All strategies select Giles + B.Fernandes -> Gabriel + Mbeumo, then HOLD, HOLD:
**148.26775**, versus independent production HOLD **147.42035**, an improvement of **0.84740**.
The guard preserves the incumbent on ties, inferior candidates, nonfinite outputs, exceptions or
unfinished work. Production's own corrected HOLD-vs-TRANSFER comparison remains unchanged.

## Independent references and recall

Recomputed through native actions, XI optimization and terminal value:

- Incumbent: HOLD, then native K2, then HOLD =147.42035.
- Known K2: Giles + B.Fernandes -> Gabriel + Mbeumo, HOLD, HOLD =148.26775.
  Naturally generated at rank1 in A/B/C. Its suffix was not lost: GW9 has at most24 nodes under
  the fixed root, all fit beam40; GW10 orders complete objective including terminal FT before trimming.
- Known K3: De Cuyper + Sels + B.Fernandes -> Gabriel + Mbeumo + Raya, HOLD, HOLD =148.61620.
  Absent in A/B/C. Its linear surrogate is166.63955, below the weakest generated K3 in A167.21420,
  B167.11550 and C166.88210. It passes **every** C structural cut (minimum observed Hamming4),
  so finite surrogate allocation, rather than diversity exclusion or future pruning, causes this miss.
  The known complete-objective gap versus the best generated package remains **0.34845**.

C adds17 packages beyond A+B, but no best-per-K objective improves over B. There is no evidence
here of realised out-of-sample superiority. Do not tune the generator or expand future actions as
an automatic follow-up. Phase3 production-readiness is deferred pending an explicitly scoped task
addressing candidate recall and operational latency; production integration remains unauthorized.

## Bounded runtime, caches and memory

Budget:900s total experimental stages,80 unique evaluations; A first, B/C only with remaining
worker allowance. Completed within budget at **612.09s**,68 unique evaluations; no PARTIAL series.

| Strategy | Generation incl. boundary, s | Native package validation, s | V3 incl. replay/cache lookups, s | Total strategy, s |
|---|---:|---:|---:|---:|
| A | 7.340 | 0.010 | 210.929 | 218.603 |
| B | 14.158 | 0.018 | 176.495 | 192.109 |
| C | 11.436 | 0.012 | 126.421 | 140.260 |

Independent incumbent search59.036s; independent setup/references61.122s overall. Total generation
32.935s; native candidate validation0.041s; V3 calls incl. lookups/replay513.845s. Inside the latter,
native unique searches408.160s and independent path replay6.831s are separately instrumented;
remaining overhead includes exact input/state hashing and cache lookup. B/C reuse prior work, so
their incremental runtimes are order dependent, not standalone speed comparisons.

Caches bind exact PlanningContext ID, full input digest and default V3 configuration. State keys
include ordered player metadata, personal prices, bank, FT, GW and timestamp. Cross-context reuse
is rejected. Independent incumbent uses no challenger caches. Cache evidence:

- 60 completed-package hits; 131 future-state hits; 3,144 action-evaluation hits.
- 16,196 resulting-roster lineup hits; 21,525 per-GW projection-view hits.
- 1,569 stored future states; 37,724 evaluated state/action transitions; 21,528 lineup entries;
  three projection views and68 completed roots.
- Parent observed OS peak working set291.04MiB; solver peaks A94.47/B96.18/C96.51MiB.

The original CLI completed every search/checkpoint, then exited1 during final memory collection:
ctypes treated a Win64 process handle as32-bit. The reader is corrected and has a regression test.
The live Windows `PeakWorkingSet64` was independently sampled every2s. Final evidence was assembled
from saved checkpoints and all68 serialized paths were replayed without repeating search.
`finalize_evidence.py`, `parent_peak_observed.json` and `serialized_path_replay.json` retain that
recovery transparently. The612.09s total sums measured setup/A/B/C stages; it excludes module import,
the later evidence repair and focused tests. No claim is made that the original CLI exited0.

## Verification and changed files

Final focused verification: **74 passed in104.75s**. Tests cover canonical legality, bank,
FT4/5 and hits, K0..5, atomic packages, cache identity, deterministic real worker generation,
reduced exhaustive surrogate agreement, structural cuts, version/integrity checks, duplicate
rejection, objective replay, failure fallback and the Win64 memory reader.

Command: `.venv/Scripts/python.exe -m pytest tests/test_cpsat_transfer_packages.py
tests/test_cpsat_phase2_candidates.py tests/test_cpsat_phase2_v3.py tests/test_strategic_planner_v3.py
tests/test_planning_context.py tests/test_packaging_spec.py tests/test_developer_tooling.py
tests/properties -q`. Hypothesis, reduced exhaustive surrogate oracles, deterministic repeated A/B/C
workers, atomic native packages and K0..5 objective replay all passed. Ruff E4/E7/F, changed-file
compile checks and strict OpenSpec validation passed. The protected-file hash guard covers329 files,
including accepted Phase1 source/tests, production, config, frozen artifacts, account/report data,
dependencies and root/dist EXEs.

New implementation: `scripts/diagnostics/cpsat_phase2_{worker,candidates,v3,benchmark}.py`.
New tests: `tests/test_cpsat_phase2_candidates.py`, `tests/test_cpsat_phase2_v3.py`.
Documentation: this file, AGENTS.md and the existing `fpl-cpsat-transfer-optimizer` OpenSpec artifacts.
No production caller, export, configuration, dependency or packaging changes are required.

Skipped: full suite, GUI/EXE work, production integration, new V22, Chip Screen and provider/account
calls. Remaining risks are candidate recall, approximate future search and latency, not native legality.

# CP-SAT Phase1: diagnostic legal transfer packages

**Phase1 PASS. Ready for separately authorized Phase2 experiments; no production integration.**

## Implementation and isolation

Native adapter: `scripts/diagnostics/cpsat_packages.py`; isolated JSON CP-SAT worker: `scripts/diagnostics/cpsat_worker.py`; frozen evaluation: `scripts/diagnostics/cpsat_gw8.py`; tests: `tests/test_cpsat_transfer_packages.py`. OpenSpec proposal/spec/design/tasks updated for Phase1; the initial planning artifacts are retained in scratch evidence. Stable production specs are unchanged.

Normal `.venv` reads canonical domain/projection/rule inputs, then invokes `.venv-solver/Scripts/python.exe`. Only the separate worker imports OR-Tools9.15.6755. No dependency installation or normal `.venv` version change. All324 protected source/asset/config/spec/account/projection/report/EXE hashes remain unchanged. No V22 regeneration, Chip Screen, provider refresh, account mutation or EXE build.

## Mathematical scope

Boolean x_p denotes each player in the FINAL15. Canonical position quotas and club cap3 apply to that final roster. Exactly K owned players leave and K eligible incoming players enter. Bank = initial bank + authoritative personal sale proceeds - current buying prices >=0, in integer0.1m. No intermediate-prefix constraints: atomic funding and club rotations are valid.

For each K0..5 independently, maximize **sum of all15 existing `ev_next_3` signals minus native transfer hits**. Signals are scaled by1,000,000 and rounded half-even. It is explicitly a LINEAR SURROGATE; no XI, captaincy, bench realization, future actions or terminal FT value. Full V3 is NOT modeled. Maximum rounding error per roster objective is0.0000075 points; comparisons may have twice that error. OPTIMAL is scoped to the exact scaled model/universe, K and prior no-good exclusions; no claim about original floating rankings or best V3 plan.

After each roster S, sum(x_p for p in S)<=14 excludes it. Up to five independent candidates per K, one worker, seed42, sorted inputs, no randomized search, zero absolute/relative gap limits. Default1s/solve; GW8 uses2s/solve. Total subprocess timeout is6*allocation*limit+30s overhead. Wall-clock-limited FEASIBLE prefixes are not universally deterministic; repeated tested outputs were identical.

Every package is reconstructed using native `_make_action` (diagnostic maxK5 config) or canonical HOLD/FT, then native validate_squad checks final roster/positions/clubs. Exact OUT/IN, resulting IDs, prices/bank, hits, FT and surrogate are compared. Mismatches raise. FT4/K0..4 has zero hits, FT4/K5 has4; FT5/K0..5 has zero; rollover uses native next_free_transfers with the cap5. HOLD remains valid.

## Tests and exhaustive scopes

11 Phase1 tests PASS (including three scaling cases and one Hypothesis property with five deterministic examples). Combined with33 native/planner/report/packaging/property/tooling tests,44 distinct focused tests pass. Tests were written before implementation. Tiny native legal enumeration matches the exact SAME integer surrogate when the solver reports OPTIMAL; they also assert distinct per-K allocation/count and native replay. Hypothesis varies bank, FT and personal selling prices and compares exact surrogate optima. Insufficient/unaffordable pools, exact club caps, repeated solves, forged output, nonfinite inputs and duplicate IDs are covered. FEASIBLE stays FEASIBLE with a gap; UNKNOWN/MODEL_INVALID handling is induced by mocks and returns no fabricated packages. NaN/bad bounds fail validation.

| Reduced fixture | Universe | K0..K5 legal package counts |
|---|---:|---|
| normal_K1_K2_tight_bank | 19 | 1, 4, 6, 4, 1, 0 |
| atomic_K3_funding | 18 | 1, 0, 0, 1, 0, 0 |
| atomic_K4_club_rotation | 19 | 1, 0, 0, 0, 1, 0 |
| K5_FT5 | 20 | 1, 7, 16, 16, 7, 1 |
| K5_FT4 | 20 | 1, 7, 16, 16, 7, 1 |

These are synthetic reduced exhaustive cases, not historical/PIT or full-production objective proof.

## Frozen real GW8

Verified context `9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208`, V22 projection run `20261022T071806Z`; existing immutable Decision/account inputs and artifact hashes verified, no refresh. Universe: 668 unique players =15 owned +653 incoming; no heuristic shortlist or exclusions. This is the declared universe, not proof about unprovided players.

Counts K0..5: **1,5,5,5,5,5**. All26 package attempts OPTIMAL, objective=bound, native legality PASS. One further K0 attempt is INFEASIBLE after its only roster was excluded; the original HOLD model is feasible. Other statuses were not observed on this GW8 run. Repeated candidate lists are identical.

Primary adapter total 2.1790s; solver loop 1.3763s. Worker peak 89.35MiB; native parent peak 226.24MiB (separate processes; not a summed simultaneous peak). Per-attempt wall/deterministic time is in the JSON.

### Every generated package, ranked separately within K

Objective/bound below are scaled-surrogate points after hits, **not V3 complete objective**. Bank is integer0.1m. All listed statuses OPTIMAL and native replay PASS.

| K | Rank | OUT | IN | Surrogate = bound | Bank | Hit | Next FT |
|---:|---:|---|---|---:|---:|---:|---:|
| 0 | 1 | HOLD | - | 162.81285 | 0 | 0 | 5 |
| 1 | 1 | Giles | Dasilva | 164.21210 | 0 | 0 | 4 |
| 1 | 2 | Giles | Thomas | 164.10830 | 0 | 0 | 4 |
| 1 | 3 | De Cuyper | Van Hecke | 163.88095 | 1 | 0 | 4 |
| 1 | 4 | De Cuyper | Konsa | 163.56265 | 4 | 0 | 4 |
| 1 | 5 | Kelleher | Petrović | 163.46760 | 5 | 0 | 4 |
| 2 | 1 | Giles, B.Fernandes | Gabriel, Mbeumo | 166.55945 | 1 | 0 | 3 |
| 2 | 2 | Giles, Groß | Gomez, Van Hecke | 165.72205 | 0 | 0 | 3 |
| 2 | 3 | Egan, B.Fernandes | Gabriel, Mbeumo | 165.69825 | 2 | 0 | 3 |
| 2 | 4 | Justin, B.Fernandes | Gabriel, Mbeumo | 165.42755 | 6 | 0 | 3 |
| 2 | 5 | Giles, Groß | Schlager, Van Hecke | 165.40625 | 0 | 0 | 3 |
| 3 | 1 | Giles, Justin, B.Fernandes | Gabriel, Mbeumo, Konsa | 167.69580 | 0 | 0 | 2 |
| 3 | 2 | Giles, De Cuyper, B.Fernandes | Gabriel, Mbeumo, Van Hecke | 167.62755 | 2 | 0 | 2 |
| 3 | 3 | Giles, Groß, Haaland | Gabriel, Thiago, Mbeumo | 167.61455 | 20 | 0 | 2 |
| 3 | 4 | Giles, De Cuyper, B.Fernandes | Gabriel, Mbeumo, Konsa | 167.30925 | 5 | 0 | 2 |
| 3 | 5 | Giles, Kelleher, B.Fernandes | Gabriel, Petrović, Mbeumo | 167.21420 | 6 | 0 | 2 |
| 4 | 1 | Giles, Egan, Groß, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke | 169.33990 | 12 | 0 | 1 |
| 4 | 2 | Giles, Groß, Kelleher, Haaland | Gabriel, Thiago, Mbeumo, Raya | 169.25535 | 9 | 0 | 1 |
| 4 | 3 | Giles, Groß, Sels, Haaland | Gabriel, Thiago, Mbeumo, Raya | 169.21310 | 9 | 0 | 1 |
| 4 | 4 | Giles, Groß, Justin, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke | 169.06920 | 16 | 0 | 1 |
| 4 | 5 | Giles, Egan, Groß, Haaland | Gabriel, Thiago, Mbeumo, Konsa | 169.02160 | 15 | 0 | 1 |
| 5 | 1 | Giles, Egan, Groß, Kelleher, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke, Raya | 166.98070 | 1 | 4 | 1 |
| 5 | 2 | Giles, Egan, Groß, Sels, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke, Raya | 166.93845 | 1 | 4 | 1 |
| 5 | 3 | Giles, Groß, Kelleher, Justin, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke, Raya | 166.71000 | 5 | 4 | 1 |
| 5 | 4 | Giles, Groß, Justin, Sels, Haaland | Gabriel, Thiago, Mbeumo, Van Hecke, Raya | 166.66775 | 5 | 4 | 1 |
| 5 | 5 | Giles, Egan, Groß, Kelleher, Haaland | Gabriel, Thiago, Mbeumo, Raya, Silva | 166.48285 | 0 | 4 | 1 |

### Known package checks

- **K2 YES:** Giles + B.Fernandes → Gabriel + Mbeumo, native legal, surrogate166.55945; generated as top K2.
- **K3 NO:** De Cuyper + Sels + B.Fernandes → Gabriel + Mbeumo + Raya is in the universe and native legal. Its surrogate166.63955 is below the fifth proven K3 candidate167.21420 (gap0.57465). The cause is surrogate ranking under the five-package allocation, not missing players or a constraint. References are checked only after generation and never injected into solver inputs.

## Readiness and remaining limits

Ready YES for a separately authorized Phase2 that evaluates these candidates with the unchanged complete V3 objective. Phase2 was not implemented. Surrogate ranking can omit superior V3 packages (as the known K3 demonstrates); no global V3 or realised out-of-sample superiority claim. The prior beam K<=5 NO-GO and its8.271 gap remain unchanged. Current candidate allocation is five/K and bounds refer to the restricted scaled model with no-good exclusions, not complete future transfer paths. No automatic archive or release.

## Reproduce only the authorized diagnostics

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_cpsat_transfer_packages.py
.venv\Scripts\python.exe scripts/diagnostics/cpsat_gw8.py
```

The adapter launches OR-Tools only using `.venv-solver`. See `openspec/changes/fpl-cpsat-transfer-optimizer/` and `scratch/cpsat_phase1_20261022/` for model inputs, full IDs, statuses/bounds, oracle scopes, preservation and runtime evidence. No full suite, expensive Chip computation, new projections or EXE build was run.

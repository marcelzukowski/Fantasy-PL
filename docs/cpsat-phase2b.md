# CP-SAT Phase2B — final bounded V3-anchored neighborhood experiment

**NO-GO toward Phase3 production-readiness validation. Keep CP-SAT diagnostic-only.**
The experiment completed, including all12 new GW8 evaluations within120s. It did not recover the
known superior K3 and missed three reduced oracle optima. There is no further tuning or production
integration in this milestone. Production V3, V22, reports, GUI, dependencies and EXEs are unchanged.

## Method and exact scope

Reuse the exact frozen GW8 context
`9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208` and existing V22
bundle `20261022T071806Z`. Verify Phase2 report integrity, candidate artifact hashes, complete
input/configuration identity,142 native source/rule hashes, and independently replay68 cached
unique paths plus the independently computed incumbent. Cache reuse does not rerun the old search.

Choose up to3 strongest K2 anchors with different incoming sets, ranked by their verified complete
V3 objectives. For each anchor and exact K3/K4/K5, solve five generic cells:

- Preserve both incoming anchor players and at least one outgoing anchor player, while requiring
  an additional incoming player at GK, DEF, MID or FWD, respectively.
- Preserve both incoming and both outgoing anchor players for a pure extension cell.

All constraints apply to the final roster, not intermediate prefixes. Native legality, personal sale
prices, bank, FT and hits remain canonical. Global no-good cuts deduplicate final rosters across
cells/anchors. There are at most45 solves/proposals (15 per anchor), with one worker, seed42,
zero gap limits and0.35s/model. The solver uses the accepted linear all15 surrogate only inside
each restricted cell. OPTIMAL therefore concerns that cell's surrogate, never the full V3 objective.

The scientific environment constructs a native optimized-XI transfer/HOLD/HOLD path for each
proposal. Its complete path value is a cheap ranking lower bound, **not a full future-search result**.
Select up to4 new packages/K, first retaining different anchors, then filling by native lower bound
and anchor V3 objective. Exclude existing Phase2 packages and duplicate final rosters. At most12
new packages receive native full future search, with unchanged K<=2/horizon3/beam40, lineup,
captaincy and terminal FT. Keep all valid cached results and the independent incumbent; exceptions,
invalid candidates and incomplete work cannot replace them.

OR-Tools9.15.6755 runs only in `.venv-solver`. The versioned JSON boundary validates context,
request/input digest, deterministic configuration, native accounting and structural cell eligibility.
No GW8 target names or IDs occur in generation or ranking. References are observation-only.

## GW8 anchors and candidate counts

All anchor evaluations were reused from verified Phase2; no new K2 search was run.

| Anchor OUT | Anchor IN | Complete V3 objective |
|---|---|---:|
| Giles, B.Fernandes | Gabriel, Mbeumo | 148.26775 |
| De Cuyper, Justin | Van Hecke, Konsa | 147.74085 |
| Giles, Groß | Gomez, Van Hecke | 147.67085 |

| Count | K3 | K4 | K5 |
|---|---:|---:|---:|
| Generated unique proposals | 15 | 15 | 15 |
| New beyond Phase2 | 10 | 10 | 10 |
| Selected for full V3 | 4 | 4 | 4 |
| Completed full V3 | 4 | 4 | 4 |

The12 new packages all passed native legality and independent complete-objective reconstruction.
The generated package list was identical on a second GW8 solve. The full search is deterministic
under the existing native configuration; earlier focused tests also check cached/uncached parity.

| K | Best cached Phase2 + new full V3 | Best new full V3 only |
|---|---:|---:|
| 0 | 147.42035 | — |
| 1 | 147.54340 | — |
| 2 | 148.26775 | — |
| 3 | 148.17525 | 147.47570 |
| 4 | 147.62200 | 147.62200 |
| 5 | 144.76755 | 144.76755 |

Final portfolio remains **148.26775**, Giles + B.Fernandes -> Gabriel + Mbeumo, then HOLD/HOLD.
Independent incumbent is **147.42035**; final advantage remains **0.84740**.
K5 improved its category by0.21450, but still does not beat the incumbent or best K2.

## Independent references and precise K3 miss

Independent native replay confirmed HOLD147.42035, known K2=148.26775 and known K3=148.61620.
The known K3 was neither generated nor evaluated as a challenger, and was never inserted manually.

Its transfer set satisfies the first anchor's K3:GK cell, including incoming retention, outgoing
overlap, final finances and legality. The single OPTIMAL surrogate winner of that cell was
Giles + Kelleher + B.Fernandes -> Gabriel + Petrović + Mbeumo, surrogate167.21420.
The target's surrogate166.63955 is lower by0.57465. Only one winner is requested per cell.
Thus the exact failure is **surrogate selection within an eligible cell**, before native future
search or the12-package allocation. Other anchors fail incoming-retention requirements for the
target. No future pruning caused this miss. The best portfolio remains0.34845 below the known path.

## Six reduced oracle contexts

Oracle scope: enumerate every legal current K0..5 package and evaluate each through the same
unchanged bounded native future search. The truth table is consulted for candidate values only
after anchor generation and cheap selection are fixed. This exhausts current packages in each
small universe, not the full global multi-GW search. All contexts use synthetic data, not GW8 IDs.

| Context | Generated global optimum? | Portfolio retains optimum? | Oracle | Portfolio | Gap |
|---|---|---|---:|---:|---:|
| Atomic K4 club rotation | NO | NO | 237.000 | 149.000 | 88.000 |
| FT5 | NO; optimum already at K1/K2 | YES | 423.851 | 423.851 | 0 |
| Constrained funding / atomic K3 | NO | NO | 220.000 | 149.000 | 71.000 |
| Strong K2 with better K3 extension | YES | YES | 196.000 | 196.000 | 0 |
| Best K3 outside K2 anchor incoming sets | NO | NO | 341.000 | 340.600 | 0.400 |
| HOLD strictly dominates transfers | Not applicable: generator proposes K3..5 | YES | 292.000 | 292.000 | 0 |

Atomic K4 and constrained funding have no legal K2 anchor; final packages are legal while proper
prefixes fail. Anchored generation therefore emits nothing. Native validation never rejects the
complete optimum: it is outside the generator's anchor reach. In the disconnected K3 case, every
chosen anchor retains an incoming player absent from the optimal K3. K4/K5 neighbors are generated
but their best complete objective remains0.4 lower. This is a structural limitation, not overfitting
evidence hidden by incumbent fallback. FT5 retains its earlier K2 optimum and generates/selects
the per-K3/K4/K5 optima. HOLD stays selected when every transfer is inferior.

All six oracle executions and native accounting/replay passed; **coverage acceptance failed** in
three contexts. The oracle run took44.24s, within its separately declared180s bound.

## Runtime and caches

| GW8 stage | Seconds |
|---|---:|
| Verify/replay cached unique paths and incumbent | 8.563 |
| First CP-SAT generation incl. boundary | 12.280 |
| Repeat generation for deterministic check | 12.606 |
| Generation total incl. validation/overhead | 24.932 |
| Native package validation, both generations | 0.032 |
| Cheap native HOLD-suffix ranking | 2.682 |
|12 full V3 calls incl. replay/cache checks | **115.286** |
| GW8 incremental total incl. references | **153.830** |

The120s deadline covers incremental new full V3 evaluation including replay/cache checks. No
evaluations were skipped or incomplete; pending=[] and failures=[]. Within those calls, native
future search100.397s and independent replay1.191s are separately instrumented. Generation, cache
verification and deterministic repeat are outside the120s evaluation clock and included in total.
GW8 plus six oracle experiments took198.073s; focused tests are reported separately. This is less
work than Phase2, not a controlled standalone algorithm speed comparison.

Reused68 unique Phase2 packages from128 strategy records, checking all artifact/input identities.
Completed-package cache grows to80. Native shared-cache hits:19 future states,492 action
evaluations,1,548 resulting-roster lineups and5,304 projection views. Three projection views are
scoped to this exact context. No cross-context or stale result reuse is permitted.

## Verification and outcome

**85 focused tests passed in108.70s**, covering Phase1/2/2B, native V3, PlanningContext,
packaging/dependency isolation and existing property tests. Hypothesis checks and real reduced
worker determinism passed. Tests include worker failure, invalid candidate rejection, incumbent
fallback, context/config/artifact mismatch, deduplication, native HOLD-suffix reconstruction,
full-objective parity and the12-candidate/deadline contract. Ruff, compile, strict OpenSpec and
the protected-file guard are recorded with the final verification evidence.

New files: `scripts/diagnostics/cpsat_phase2b.py`, `cpsat_phase2b_worker.py`,
`cpsat_phase2b_candidates.py`, `cpsat_phase2b_benchmark.py`, `cpsat_phase2b_oracles.py`;
`tests/test_cpsat_phase2b.py`, `tests/test_cpsat_phase2b_candidates.py`; this document.
Updated AGENTS.md, the existing OpenSpec change and focused algorithm guidance.
Evidence: `scratch/cpsat_phase2b_20261022/{results,candidates,candidates_repeat,oracles,verification}.json`.
Phase1/2 code and evidence remain unchanged, along with346 protected source/data/dependency/EXE files.

Stop/go gates: objective/legality/FT, incumbent protection, determinism and bounded evaluation pass;
known K3 recovery and acceptable oracle coverage fail. **NO-GO.** Keep production stable K<=2 and
CP-SAT diagnostic-only. Do not start another heuristic cycle or integration without a new task.

Skipped: full suite, production integration, providers/account calls, projections, Chip Screen,
GUI/EXE work. Remaining risks are candidate recall, anchor reach and latency; there is no claim
of global multi-GW optimality or realised out-of-sample superiority.

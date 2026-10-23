# Manual Transfer Comparator

The Transfer Comparator tab evaluates a user-selected simultaneous K0..5 package. It does not generate packages or change the production recommendation. Production V3 remains K<=2, including the corrected complete-objective HOLD comparison and existing terminal FT valuation. Market Shadow influence remains false; CP-SAT and challenger modules remain diagnostic-only.

## Workflow and scope

Load the current verified compatible V22 context explicitly. Tick a checkbox or click a row in either OUT or IN to select/deselect a player. Both tables have independent 0/5..5/5 counters and the same checked-row styling, search, position/club/price filters, selected-only view and local sorting. Hidden choices survive filtering and sorting. No Add incoming button is needed. Equal OUT/IN counts are required for a complete package; either side may be selected first. Validation uses native final-squad rules and personal selling values before enabling evaluation. HOLD resets both selections. Final squad, bank, initial/next-GW FT and hit points are shown before evaluation.

Evaluate runs native V3 with the selected current-GW package fixed and the existing approximate three-GW search (future K<=2, beam width 40). Complete objective includes path points after hits and terminal FT value. HOLD means HOLD **now**, with native future planning; it does not mean HOLD throughout all three weeks. An independent unchanged production V3 run supplies the production baseline. All comparisons share the same PlanningContext and verified input digest. None is a global-optimality guarantee.

Save, rename, load and delete named scenarios locally. The comparison table wraps complete OUT/IN, XI and future-path text and scrolls as needed. Scenarios are stored atomically in `data/user/manual_transfer_scenarios.json`; corrupt files are preserved and reported. Equivalent packages in the same context are deduplicated. Changed context, prices, ownership, FT, bundle integrity or inputs invalidate scores. Old transfers can be explicitly reconstructed and re-evaluated, subject to current legality. Existing Decision/Chip reports are never rewritten.

## Worker and packaging boundary

The GUI imports only the widget/store and existing lightweight orchestration. A persistent on-demand QProcess starts the project's external `.venv/Scripts/python.exe -m desktop_app.manual_scenario_runner`. The worker verifies V22 artifacts and PlanningContext, validates atomic packages and delegates scoring to unchanged native V3. It never uses `.venv-solver`, OR-Tools or diagnostic generators.

Progress, errors and context-scoped results use JSON lines. Native evaluation has a 180-second deadline; the GUI also enforces a timeout. Cancellation terminates its own worker and clears its active results; context must be loaded again. A Windows parent watchdog handles the venv redirector's actual Python child, including cancellation during scientific import. Normal window close shuts down the worker. No worker or provider request starts merely by opening the tab/application. Temporary request snapshots are deleted on shutdown. No account submission API is used.

## Verification, 2026-10-23

Frozen GW8 PlanningContext: `9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208`, verified projection run `20261022T071806Z`. The existing projection artifacts, account state, production planner and historical reports were checked against the pre-task SHA-256 snapshot and remained unchanged.

| Explicit native path | Complete objective |
| --- | ---: |
| HOLD / HOLD / HOLD | 146.12210 |
| HOLD now / De Cuyper + Groß to Van Hecke + Tonali / HOLD | 147.42035 |
| Giles + B.Fernandes to Gabriel + Mbeumo / HOLD / HOLD | 148.26775 |
| De Cuyper + Sels + B.Fernandes to Gabriel + Mbeumo + Raya / HOLD / HOLD | 148.61620 |

The requested all-HOLD reference label was inconsistent with the frozen engine: **147.42035 is the optimized HOLD-now baseline**, not the all-HOLD path. The independent native replay gives all-HOLD path points 141.12210 plus terminal FT value 5.00000. Production code hardcodes neither these names nor these values.

- New focused tests: 27 passed (K0..5, atomic funding/club rotations, quotas, bank/personal prices, FT4/K5 hit4, FT5/K5 hit0, HOLD5 cap5, native objective reconstruction, XI/captain, Hypothesis, cache/stale input, store/UI/error/cancellation). The actual Windows child process is verified exited after cancellation.
- Existing focused V3/Decision/StrategyPreview/GUI/orchestration/PlanningContext/packaging tests: 76 passed.
- `scripts/dev/check.py`: PASS, including Ruff, formatting, diff checks and 33 contract/property tests; some overlap the preceding suites. New modules/tests also pass Ruff E4/E7/F and formatting.
- Source GUI with real scientific worker: HOLD 16.23s including both baselines; cached-context K2 5.01s, K3 5.61s. Cancellation 0.0045s; GUI timer remained active (maximum observed gap 0.328s including loading/rendering).
- Existing lightweight ONEFILE spec: build PASS; archive contains comparator/store, excludes scientific stack, OR-Tools, evaluator/runner and diagnostic modules. External project source and `.venv` remain required.
- Actual dist EXE, native Windows UI automation and screenshots: startup, context loading, invalid-package blocking, K2/K3 evaluation and values, FT4/K5 hit4, side-by-side results, full XI/captain/VC/path rendering, save/rename/reload/delete, cancellation, context reload and normal close PASS. Owned worker/redirector/conhost PIDs exited after cancellation and normal close. K2/K3 approximately 7.91s/7.96s including UI automation overhead. Smoke-only saves were removed through the UI; no user scenarios existed before this smoke.

Local evidence is in `scratch/manual_comparator_20261023/`: native `references.json`, `source_smoke.json`, archive check, build log, packaged saved-result evidence, UI accessibility snapshots/screenshots, worker trees, shutdown result, protected-input snapshot and release identity. These are verification artifacts, not production inputs.

## Release gate

Previous validated table-release root/dist build: 78,861,896 bytes, SHA-256 `075727a3c1e3005ebbded11fd39daffeb9f7a82cb9730163bd97f0b79918a67a`. The current reliability release is recorded below.

The validated dist candidate was copied to the project root after the user manually closed the previous application and no instance used the destination. Root and dist both have the size and SHA-256 above. One root launch confirmed the FPL Control Center window and Transfer Comparator tab, with no startup Python worker. The application closed normally and all owned processes exited. Promotion, identity checks and root smoke passed; all OpenSpec tasks, including the analytical-table follow-up, are complete. No application process was forcibly closed for replacement.

No new V22 projections, Chip Screen, provider refresh, expensive full analysis or full test suite was run. Existing Decision/Chip integration and production recommendation scoring were preserved.

## OUT selection usability follow-up, 2026-10-23

Inspection confirmed the owned QListWidget already stored native check states, but relied on default list indicators and restricted mouse toggling to the indicator. The fix keeps those check states as the sole OUT source of truth: scoped high-contrast 22px checkboxes use an included check SVG, whole-row clicks toggle once, checked rows are tinted/bold, and a visible counter tracks 0/5 through 5/5. A sixth selection is rejected with an explanation. Deselection, saved-package reload and Reset to HOLD update the same styles/count. Each edit immediately discards the current result and stale financial preview; unequal OUT/IN counts are explained and evaluation stays disabled. Complete packages still use the existing debounced canonical scientific-worker validation.

Only the comparator widget, checkbox asset and focused UI tests changed in runtime/test sources. Native V3, scoring, worker, local scenario store, main window integration, spec and protected account/report/projection artifacts remained byte-identical to the pre-fix snapshot.

- 49 focused comparator/native V3/GUI-layout/packaging tests passed; Ruff passed.
- `scripts/dev/check.py` passed, including its 33 contract/property tests (overlap with the focused selection).
- Actual dist Windows GUI: 20 coordinate-based mouse clicks exercised checkbox and row selection, deselection, counter 0..5, rejected sixth selection after scrolling, mismatched OUT/IN, Reset to HOLD, incoming selection and evaluation. Visual screenshots confirm the checked tick, row tint and bold text. The canonical K2 preview gives bank £0.1m, hit0 and next-GW FT3; evaluation still gives 148.26775 (23.03s including cold baseline computation). Editing OUT after evaluation clears eligibility/preview immediately.
- Lightweight build/archive, normal dist close with no orphan workers, root promotion/hash equality and root launch/normal close passed. Scientific packages remain excluded and external `.venv` is still required. No user processes were force-closed.

Evidence: `scratch/manual_out_usability_20261023/`, especially `dist_mouse_smoke.json`, checkbox/five-selected/result screenshots, root smoke, protection snapshot and final release identity.

## Twin analytical selection tables, 2026-10-23

OUT and IN now share a lightweight Qt model/view implementation. Checkbox, whole-row click and Space use the same selection path, with a five-player limit on each side. Filters and sort order operate on the loaded dataset and preserve canonical selected IDs. IN defaults to Next 5 GW total descending; OUT defaults to owned order. Both can sort by name, position, club, price, season points, next-GW xP and five-GW xP, with Asc/Desc and unknown values last. Selected-only makes hidden choices easy to review. A horizontal splitter gives approximately 30/48/22 OUT/IN/finance widths; a vertical splitter adjusts selection versus result height. The scenario result table and all local persistence remain intact.

IN displays name, position, club, buying price, season points, next-GW xP, five-GW total and a combined fixtures/projected-points column. OUT shows corresponding owned metrics and personal selling prices. Season points come from verified `current_players.json` provider snapshots. GW totals come from the existing V22 bundle; fixture identities/opponents/venue come from verified `fixture_horizon.json` and existing club assets. The worker already checks both artifact hashes. Five-GW means the current upcoming GW through GW+4; it does not mean five arbitrarily truncated fixtures. Totals require all five GW values. Fixture xP is assigned from a GW total only when the projection declares exactly one matching fixture for that player's club and GW. DGW totals are never divided or repeated per fixture; unknown fixture values stay `—`, with available GW totals and coverage in tooltips. These are display metrics; scenario scoring remains the unchanged three-GW native V3 objective.

In the verified GW8 context all 653 incoming candidates have season points, complete five-GW projections and five identified single-fixture GWs: 3,265 fixture/xP entries, with no inferred fixture split. No provider refresh or projection generation was run.

Verification:

- 60 focused UI, metadata, native evaluator/V3, persistence, layout and packaging tests PASS; Ruff PASS. Coverage includes mouse parity, both limits, selection retention under filters, selected-only, numeric/name sorting, missing values, complete metadata rendering, DGW/missing metadata, preview invalidation and worker cancellation. A 700-row local sort/filter check stays below its two-second test budget.
- Raw developer gate PASS, including its 33 contract/property tests (overlap with the preceding selection).
- Actual dist EXE PASS: native mouse selection on OUT/IN and sort-menu items; default five-GW order; descending season points, next-GW and five-GW sorting; fixture/xP rendering; hidden selections, selected-only, canonical K2 bank/hit/FT preview, evaluation, edit invalidation and Reset to HOLD. The recorded workflow contains 14 mouse clicks and reproduces 148.26775 in 22.77s including cold baseline evaluation. Dist normal close leaves no owned workers.
- Lightweight archive includes the shared table module and excludes scientific/solver/diagnostic packages and the external runner. The accepted spec is unchanged. Root promotion, root launch/normal close and matching root/dist size/SHA-256 PASS.
- Protected production V3, canonical evaluator, FT rules, worker guard, store, main-window integration, spec, account state and historical report/projection inputs remained byte-identical. Worker changes expose metadata only; no report schema, chip or scoring changes.

Evidence: `scratch/manual_comparator_tables_20261023/`, including metadata probe, source/packaged screenshots, packaged table smoke, root smoke, build log, protected-input snapshot and final release identity.

## Reliability follow-up, 2026-10-23

Saved results now require complete compatible identity and structural/arithmetic path validation before displaying evaluated scores. Invalid results preserve reconstructable OUT/IN selections and explain re-evaluation; reads do not rewrite stored payloads. Worker startup/structured initialization errors clear busy state and retain diagnostics. See [production reliability fixes](production-reliability-fixes.md) for scope, regressions and release evidence.

Current validated root/dist: **78,869,641 bytes**, SHA-256 `4befb95fcdbf71e84abb7af3a5100dcfd51d8f96907b848036ef5a3d46f56ff1`. Focused integration226 PASS; raw gate33 PASS (overlap); lightweight build, actual dist recovery/re-evaluation/normal-close, root promotion/launch/normal-close and root/dist identity PASS. Native HOLD-now complete objective remains147.42035. Production V3/V22/Chip, FT and atomic evaluator mathematics are unchanged; no live providers/projections/Chip computation or user-process force-close.

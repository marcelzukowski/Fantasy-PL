# Agent guidance

This is the concise, actionable project entry point. The complete previous handoff is preserved byte-for-byte in [AGENTS-history.md](docs/agents/AGENTS-history.md); consult it for historical milestones and detailed legacy contracts. Focused current guides:

- [Architecture and data lineage](docs/agents/architecture-data-lineage.md)
- [Optimization and objective fidelity](docs/agents/optimization-objective-fidelity.md)
- [Oracle and property tests](docs/agents/oracle-property-tests.md)
- [Production safety and release](docs/agents/production-safety-release.md)
- [Developer tools and raw quality checks](docs/developer-tooling.md)
- [Algorithm change workflow](openspec/README.md)
- [Manual Transfer Comparator and release verification](docs/manual-transfer-comparator.md)

## Project

Fantasy-PL is a 2026/27 FPL prediction and decision engine with the FPL Control Center desktop GUI. Production projections use `fixture_simulator_v22_lineup_coherent_logit` (V22). Keep user-facing recommendations tied to the actual squad, personal prices, bank, free transfers, constraints, availability, horizon, hits and chip state.

## Working rules

- Read this file and the relevant focused guide before changing code. Inspect the live implementation and all callers first.
- Keep changes scoped to the task. Preserve existing user edits; do not reset, overwrite, or “clean up” unrelated work.
- Treat `scratch/` as evidence or experiments, never as production by recency alone. Record artifact identity and lineage for consequential runs.
- Do not run expensive projections, full analysis, Chip Screen, provider refreshes, packaging, or broad suites unless the task explicitly requires them. Avoid routine release work without a task.
- Use the existing external project `.venv` for lightweight GUI worker processes. Never run `uv sync` or install/synchronize dependencies without an explicit task.
- Keep FPL account access read-only. Preserve entry ID, purchase/selling-price maps, bank and free-transfer state; never expose credentials, bearer tokens, or secrets in output or files.
- Market Shadow production influence must remain false unless a separately reviewed task changes that contract.
- Never claim an optimizer is optimal without stating its mathematical model, solver status, and exact search scope. Label measurements, guarantees, approximations, and untested assumptions distinctly.
- Do not describe a milestone as complete when a required gate failed or was skipped. Report checks and material limits accurately.

## Stable decision-planner facts

- Stable V3 evaluates at most K<=2 transfers per action/gameweek and uses beam search, so it is approximate and is not proven globally optimal.
- Final selection compares complete objective values for HOLD and unrestricted search; HOLD wins exact ties and differences within `1e-9`.
- K<=5 expansion remains deferred: the guarded portfolio missed an exhaustive adversarial case by `8.271` objective points. Do not enable or restart heuristic expansion without a new scoped task.
- Production V22 and the existing Decision/Chip integration are stable. Do not silently substitute a scratch run or challenger for production.

## Change completion

For code changes, make the smallest complete fix across callers and relevant tests. Verify only the requested scope and report changed files, checks, skipped checks, and remaining risks. Update the relevant focused guide only when its durable contract changes. Keep this entry point concise; put detail in the focused guides.

## Developer tools

- Reuse the existing Serena MCP and symbol/reference navigation. Use Context7/official documentation for library and CLI setup.
- Run `.venv/Scripts/python.exe scripts/dev/check.py` for fast raw checks; the installed pre-commit hook uses `--staged`. Never compress away failures, tracebacks, security warnings or build errors.
- Use OpenSpec for algorithm proposals, tests before implementation and explicit verification before archive. CP-SAT stays diagnostic-only; [Phase2B final evidence](docs/cpsat-phase2b.md) records NO-GO: known K3 miss and atomic/disconnected oracle failures. OR-Tools stays in `.venv-solver`, outside GUI/production imports. Keep stable production K<=2; no further heuristic cycle or integration without a new scoped task.

## Changelog

- 2026-10-23 — AUDIT-RELIABILITY — Fixed invalid saved Comparator result reuse, worker startup/initialization recovery and canonical Market Shadow advisory status. 226 focused tests and raw quality gate passed; lightweight dist/root smoke and promotion/hash equality passed. Production engine/account/historical artifacts preserved. See [reliability verification](docs/production-reliability-fixes.md); no unrelated audit recommendations implemented.

- 2026-10-23 — COMPARATOR-TABLES — Added twin checkbox OUT/IN model/view tables, local sorting/filtering, verified season/next-GW/5-GW/fixture display metadata and adjustable analytical layout. 60 focused tests, raw developer gate, packaged table/mouse/evaluation workflow and root promotion/launch/normal close passed; root/dist identity matches. Display-only changes preserve native V3/canonical evaluation/FT/Chip/report semantics. Unknown DGW fixture splits are not invented; see comparator documentation.

- 2026-10-23 — COMPARATOR-OUT-UI — Made native OUT checkboxes explicit, added checked-row styling and a 0/5..5/5 counter, whole-row toggling and immediate count-mismatch/preview invalidation. 49 focused tests and the raw developer gate passed; 20 mouse clicks in the actual dist EXE, normal worker shutdown, root promotion/launch and root/dist identity passed. Canonical validation and all production/worker/scenario-store logic preserved. See comparator verification.

- 2026-10-23 — MANUAL-TRANSFER-COMPARATOR — Added the explicit read-only K0..5 comparator with native V3 future K<=2 evaluation, same-context baselines, local scenarios and an external scientific worker. Production V3/V22/Decision/Chip and diagnostic isolation preserved. Focused tests, actual dist workflow and root promotion/launch/normal close passed; root/dist size and SHA-256 match. See comparator documentation for evidence and the corrected GW8 all-HOLD reference label.

- 2026-10-22 — CPSAT-PHASE2B — Final bounded anchored-neighborhood experiment completed:12 new GW8 evaluations in115.29s, portfolio unchanged148.26775, known K3 not recovered. Six reduced oracles expose gaps88/71/0.4; NO-GO and diagnostic-only.85 focused tests passed; production and prior evidence preserved. See Phase2B report; no automatic optimization follow-up.

- 2026-10-22 — CPSAT-PHASE2 — Completed bounded A/B/C frozen GW8 comparison: 68 unique native-replayed packages, best148.26775 versus incumbent147.42035; all strategies miss known K3=148.61620. 74 focused tests passed. Production, Phase1, account/projection/report data and EXEs preserved. See Phase2 evidence for cache/timing, telemetry recovery and promotion limits; no automatic integration or optimization follow-up.

- 2026-10-22 — CPSAT-PHASE1 — Added isolated final-roster K0..5 generation, canonical native replay and reduced exact-surrogate/property tests. Frozen GW8 results and limitations are documented separately; production V3 and dependencies remain unchanged. No Phase2 or EXE build.

- 2026-10-22 — DEVELOPER-TOOLING — Preserved complete prior handoff in the history archive; added focused guidance, OpenSpec, raw quality gates and property tests. Existing runtime versions and production semantics retained; OR-Tools isolated in development worker. See developer-tooling verification and limits.

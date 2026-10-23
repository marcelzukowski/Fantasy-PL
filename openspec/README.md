# FPL algorithm changes

Use **Proposal → Specification → Design → Tasks → Tests → Implementation → Verification → Archive**.
The installed `spec-driven` schema supplies proposal/specs/design/tasks. Tests and verification are
explicit tasks and gates, not extra invented artifact types. Codex workflows are generated under
`.agents/skills/openspec-*`; use `$openspec-propose` for a newly authorized change.

1. Read current specs and [agent guidance](../AGENTS.md); identify scope and lineage.
2. Create a proposal with `openspec new change <name>`. Use `openspec instructions <artifact> --change <name>`.
3. Specify acceptance scenarios, then design objective/model/scaling and tasks.
4. Add focused oracle/property tests before implementation. A solver status alone is insufficient.
5. Implement only the authorized scope; preserve the stable baseline and immutable reports.
6. Verify tests, source/data guards, search scope, solver bounds and measured latency; retain full failures.
7. Run `openspec validate <name> --strict`. Archive only when implementation and verification are complete.
   `openspec archive <name>` updates current specs; never use it to present planned work as delivered.

The new [stable baseline](specs/v3-stable-planner/spec.md) records the accepted current state; no old
specification was overwritten. The existing chronological history remains in
[AGENTS-history.md](../docs/agents/AGENTS-history.md).

`fpl-cpsat-transfer-optimizer` now contains the explicitly authorized **Phase1 diagnostic legal-package
generator**. Its linear surrogate is not full V3 and it is not integrated into production.
`openspec status --change fpl-cpsat-transfer-optimizer` reports artifact readiness; check tasks and
[Phase1 evidence](../docs/cpsat-phase1.md) for implementation verification. The separately authorized
[Phase2 experiment](../docs/cpsat-phase2.md) is now complete: native candidate scoring passes, while
production-readiness remains NO-GO. Further work requires a new scoped task.
Leave the change unarchived unless archiving is explicitly requested.

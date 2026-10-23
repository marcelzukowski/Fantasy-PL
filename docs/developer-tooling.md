# Developer tooling: verified local setup

Production source, projections, immutable reports, account state and packaging are outside this
tooling change. The current Windows Python is3.12.12; the repaired desktop `.venv` must not be
recreated or synchronized with `uv sync`. Existing user edits remain in place.

## Fast, raw checks

From the project root in PowerShell:

```powershell
.venv\Scripts\python.exe scripts/dev/check.py
```

The same command with `--staged` is installed as a local pre-commit hook. It runs:

- Ruff correctness rules E9/F63/F7/F82 on staged Python files and the new tooling/property files;
- additional E4/E7/F lint and `ruff format --check` on the new tooling/property files only;
- Python compilation of that scope, `git diff --check`, and33 fast native V3/HOLD, report,
  packaging-contract, property and tooling tests. No projections, Chip Screen, provider calls or EXE.

This is incremental adoption, not a claim that the entire legacy repository is formatted or lint-clean.
Legacy production formatting is intentionally not migrated. Checks never auto-fix files. A normal
pre-commit invocation handles partially staged work with its usual stash mechanism; this setup did
not stage, commit or stash the user's changes. `pre-commit run --all-files` still invokes this
staged-scope entry; it is not a whole-repository formatting/compilation claim.

All subprocess output is inherited verbatim. Hook `verbose: true` retains successful output and
warnings too; failure exit codes propagate. Tests explicitly verify traceback, security-warning and
build-error text remains visible. To run the hook manually within the Codex sandbox:

```powershell
$env:PRE_COMMIT_HOME = Join-Path (Get-Location) '.cache/pre-commit'
.venv\Scripts\python.exe -m pre_commit run fpl-fast-contracts --all-files
```

For a separate, deliberately expensive manual verification, after explicit task authorization:

```powershell
.venv\Scripts\python.exe -m pytest -q
# Optional offline reduced oracle research, only if explicitly requested:
.venv\Scripts\python.exe scripts/diagnostics/v3_portfolio_oracle.py
```

Neither command is run by commit hooks or by this tooling setup. Provider refresh, V22 regeneration,
historical replay and Chip Screen require their own scoped request and verified inputs.

## Existing Serena and Codex

Reused Serena2.0.0 shared with other projects; no reinstall or global config replacement.
Existing Codex CLI0.163.0 registration is:

```toml
[mcp_servers.serena]
command = "serena"
args = ["start-mcp-server", "--context=codex", "--project-from-cwd"]
```

`.serena/project.yml` already identifies Fantasy-PL, UTF-8 and Python LSP and remains untouched.
Personal Serena state/cache is ignored by Git. Current-agent MCP verification confirmed active
Fantasy-PL/context codex/LSP ready; found `StrategicPlannerV3`, references to `_actions_for_state`,
`DecisionInput` and `PlanningContext` semantically without reading their whole modules.
Use `find_symbol` and `find_referencing_symbols` with exact paths before edits.

Official setup: [Serena Codex client](https://github.com/oraios/serena/blob/main/docs/02-usage/030_clients.md).
The registered command already matches that setup, so `serena setup codex` was unnecessary.

## OpenSpec

Subsequent milestone: [CP-SAT Phase1](cpsat-phase1.md) implements the explicitly authorized isolated
legal-package generator. The setup description below records the original design-only state;
Phase2 and production integration remain unimplemented.

Reused installed OpenSpec1.14.3 and initialized `openspec init --tools codex` once. Six Codex skills
were generated under `.agents/skills`; current-agent CLI instructions, artifact status and strict
validation were exercised. No prior specs existed or were overwritten. See the
[workflow](../openspec/README.md), stable baseline and the unimplemented
`fpl-cpsat-transfer-optimizer` proposal. Planning artifacts being complete does not mean the proposed
solver is implemented; future tasks remain unchecked and the change is not archived.

Official integration: [OpenSpec supported tools](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md).

## RTK: existing integration and full-output boundary

Reused RTK0.50.0 and the existing trusted global Codex `PreToolUse` hook (`Bash` matcher,
`rtk hook codex`). No duplicate project hook or global replacement was installed. The official
protocol with `permission_mode: default` returned `updatedInput: rtk git status --short`.
The qualified quality-runner command was left unchanged. `rtk proxy` preserved a controlled failure's
full traceback, security warning, build error and nonzero exit code. No token-savings estimate is made.

This sandbox denies execution of the installed WinGet RTK binary; probes passed with approved
execution outside the sandbox. A directly rewritten `uv` command failed here, so quality gates use
qualified project Python and real executables via subprocess, not filtered shell aliases. Retain this
limitation in reports; do not call sandbox execution of RTK successful. Use raw output for all tests,
builds and security-sensitive checks, optionally `rtk proxy <command>` where the binary can execute.

Official protocol and raw mode: [RTK hook formats](https://github.com/rtk-ai/rtk/blob/develop/hooks/README.md),
[Codex integration](https://github.com/rtk-ai/rtk/blob/develop/hooks/codex/README.md).
Codex configuration and approval boundaries: [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Development dependencies and isolation

Added Hypothesis6.170.5, Ruff0.17.1, pre-commit4.7.0 and nine missing transitive distributions to
`.venv`; all previously installed versions are unchanged. Dependencies are in the `dev` group and
`requirements/dev-tools.txt`; runtime dependency declarations are unchanged. Installation used
constraints pinning every existing package. `uv lock` refreshed metadata without `uv sync` or
environment changes, retaining every prior locked package version. It also reconciled the previously
stale lockfile's missing `pytz` declaration, which already existed in `pyproject.toml`; no runtime
dependency declaration was added by this task.

Hypothesis strategies in `tests/properties` draw legal synthetic squads from native rule configuration.
Native validators/price/FT/action functions are the oracle. There is no copied production rule engine.
The scope covers roster uniqueness/quota/club rejection, affordability using personal sales and current
buys, hit/FT consistency, and atomic final-package legality. Canonical native SquadState accepts FT1..5;
FT0 is covered as an accounting-helper input and rejected as a canonical squad. This task does not
silently broaden that production contract.25 deterministic examples per property keep hooks bounded.

OR-Tools9.15.6755 has a compatible CPython3.12 Windows x64 wheel, but requires protobuf>=6.33.1,<6.34;
the existing `.venv` has protobuf7.36.1. Installing there would downgrade an existing package, so
OR-Tools is installed only in ignored project `.venv-solver`, not in `.venv`, runtime dependencies or
the GUI. Future PoC execution must explicitly use that development worker; the production external
worker boundary has not changed.

```powershell
# Recreate only the separate solver development environment on a new checkout:
.venv\Scripts\python.exe -m venv .venv-solver
.venv-solver\Scripts\python.exe -m pip install -r requirements/solver-dev.txt
.venv-solver\Scripts\python.exe scripts/dev/solver_smoke.py
```

The smoke problem is a generic integer x<=2 maximization, not an FPL engine. It returned OPTIMAL,
objective2 and bound2 with a2s limit and one worker. See the proposal design for solver statuses,
zero-gap requirements, model/universe scope, integer price units, projected-point scaling error,
execution limits and native roster/FT fidelity. Mathematical-model validity and full-universe
optimality do not follow from an installation smoke or from CP-SAT status alone.

Official sources: [CP-SAT solver](https://developers.google.com/optimization/cp/cp_solver),
[Hypothesis settings](https://hypothesis.readthedocs.io/en/latest/settings.html),
[Ruff configuration](https://docs.astral.sh/ruff/configuration/).

Verification artifacts, dependency deltas, lock metadata and production hashes are in
`scratch/developer_tooling_20261022/`. Full prior agent history is preserved byte-for-byte under
`docs/agents/AGENTS-history.md`; root agent guidance now links four focused guides.

# Design

## Context

See proposal and the completed audit A02/A01/A06. Desktop persistence trusts only a shallow result envelope; process error callbacks only log; run discovery reads a manifest section while Market Shadow publishes sidecars. Native engine and archived data are protected by a pre-change hash snapshot.

## Goals / Non-Goals

Goals: fail closed at reuse/display boundaries, preserve recoverable selections, provide terminal process states and accurate advisory provenance.
Non-goals: objective/scaling/solver/search changes, model or Chip computations, provider calls, historical artifact rewrites and unrelated audit recommendations. No solver status, bound or integer scaling changes apply; the unchanged native objective remains authoritative.

## Decisions

- Reuse current context ID and full native digest covering state, rules, projections and default evaluator configuration. Add result structural/arithmetic validation at persistence and GUI consumption, rather than recomputing expensive native paths on each render. Valid old records remain readable; invalid result content is downgraded with an explanation while valid selections survive. Malformed root JSON stays untouched.
- Handle FailedToStart separately because Qt does not emit finished for it. Normal completed failures retain existing result handling, with idempotent cleanup for cancellation/startup races. Comparator keeps its bounded initial-response timer and owned-worker guard. Do not introduce a general process framework.
- Resolve advisory sidecars by canonical season/run directory and explicit model-cutoff identity. Validate influence=false, timestamps and coverage before displaying success. A later market cutoff is advisory as-of information, not a fact available to the original model. Unsupported live RUNNING is not invented from filesystem age.
- Keep external `.venv` workers and accepted ONEFILE spec; use bounded fault injection and actual packaged workflow smoke without fresh projections/providers/Chip simulations.

## Risks / Trade-offs

- Legacy malformed results → preserve selections and explain re-evaluation; avoid destructive automatic rewrites.
- Qt error/finished ordering → targeted real missing-program and immediate-exit regressions, terminal-state idempotency.
- Sidecar schema drift → inspect actual producer contract and existing valid/invalid fixtures; never infer success from filename alone.
- User running root EXE → wait for manual closure before promotion; leave stable root intact if gates fail.

## Migration Plan

No automatic data migration. Validate regressions and source/data guards, build dist, exercise affected GUI workflows, then promote only on PASS and no running destination instance. Rollback retains the prior root release identity/backup. Archive only on a separate request.

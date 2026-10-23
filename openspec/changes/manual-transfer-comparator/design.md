# Design

## Context
The desktop is a lightweight PySide6 shell with external project .venv workers. Native V3 is
unchanged K<=2/horizon3/beam40; manual current actions can be K0..5 without generating candidates.

## Goals / Non-Goals
Deliver a complete local comparator and validated lightweight ONEFILE. Do not promote manual
winners, import diagnostic/CP-SAT code, write production reports or mutate account/projection data.

## Decisions
- A separate scientific evaluator validates simultaneous final packages through native V3 actions,
  forces only the current action, and delegates future search/scoring to unchanged native V3.
  No scaling/solver bound applies: these are floating native path values under approximate search.
- A persistent QProcess JSON-lines worker owns verified DecisionInput, independent production/HOLD
  baselines and exact-context caches. GUI startup performs no provider calls or V3 work. Explicit
  Load context starts the worker; validation is cheap and asynchronous. Evaluate is on demand.
- GUI exposes search, filters, independent OUT/IN lists (atomic packages need no pair ordering),
  final squad, canonical finance and side-by-side scrollable non-elided results. Progress, timeout,
  process errors, cancellation and shutdown are explicit. Cancellation terminates the isolated worker.
- Save named scenarios atomically in data/user/manual_transfer_scenarios.json. IDs/context/input
  hashes gate results; context changes invalidate comparisons. Explicit reload allows reconstruction
  against current ownership/prices/FT without silently accepting or reusing old evaluations.
- HOLD comparison means current HOLD with native optimized future continuation. The supplied GW8
  all-HOLD=147.42035 label conflicts with existing evidence (HOLD/K2/HOLD); independently measure
  and report all-HOLD and optimized HOLD separately, never change native objective to force a value.

## Risks / Trade-offs
First evaluation computes independent production baselines and may take up to180s; show progress
and allow cancellation. Source/data/price changes invalidate worker/cache/results before comparison.
Release only after focused tests, dist startup, actual packaged workflow, worker isolation/shutdown;
otherwise retain stable root EXE. No dependency installation or uv sync.

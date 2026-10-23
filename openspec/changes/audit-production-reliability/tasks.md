# Tasks

## 1. Saved scenario integrity

- [x] 1.1 Add failing fresh/stale/corrupt/partial-result regressions, implement non-destructive validation and document recovery; verify focused store/UI tests and native objective parity.

## 2. Worker startup recovery

- [x] 2.1 Add failing real FailedToStart and injected initialization/exit/cancel regressions, implement finite terminal/retry states and document behaviour; verify focused worker/UI tests without provider calls.

## 3. Market advisory status

- [x] 3.1 Add failing actual-sidecar-contract regression and invalid/stale/status tests, resolve validated sidecars and document timing; verify trust/discovery tests and influence=false.

## 4. Integration and release

- [x] 4.1 Run focused integration/native objective checks, Ruff, compilation, raw developer gate and strict OpenSpec validation; verify protected source/data hashes.
- [x] 4.2 Build accepted lightweight ONEFILE and smoke-test affected dist workflows plus owned-worker cleanup; promote only after PASS and manual closure of any running root, then verify root launch/normal close and root/dist SHA-256 equality.

## Workflow follow-up

- Keep this change unarchived until explicitly requested.

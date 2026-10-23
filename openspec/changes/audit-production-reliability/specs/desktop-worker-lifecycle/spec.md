## Purpose

Make scientific worker startup failures finite and recoverable without altering successful engine calculations.

## ADDED Requirements

### Requirement: Recoverable failed startup
Scientific worker creation, initialization and immediate-exit failures SHALL end busy progress, show a meaningful error with diagnostic logs, and permit recovery without restarting the GUI when feasible.

#### Scenario: Executable cannot start
- **WHEN** the configured Python executable cannot be launched
- **THEN** the workflow reaches an error or partial terminal state and retry is available.

#### Scenario: Dependency or initialization failure
- **WHEN** a worker exits before producing a usable result or fails its initial handshake
- **THEN** the GUI clears running progress and exposes the failure rather than treating the request as successful.

### Requirement: Owned process cleanup
Cancellation and failure cleanup SHALL terminate only application-owned workers and SHALL preserve prior successful analysis results.

#### Scenario: Cancel after partial startup
- **WHEN** cancellation follows failed or partial startup
- **THEN** no owned worker remains and the GUI remains recoverable without account mutation.

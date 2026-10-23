# Stable V3 planner

## Purpose

Record the accepted production decision baseline and its limitations without reinterpreting
immutable historical reports or promoting diagnostic research into production.

## Requirements

### Requirement: Stable bounded objective
Production V3 SHALL retain K<=2 actions and its current complete objective: projected lineup points
after transfer hits plus terminal FT value. HOLD SHALL win comparisons within1e-9.

#### Scenario: Accepted GW8 selection
- **WHEN** the verified GW8 context gives HOLD147.42035 versus unrestricted146.90385
- **THEN** the selected recommendation is HOLD with advantage0.51650 and matching previews.

### Requirement: Explicit approximation
Reports about the planner MUST identify approximate beam search and the K<=2 action limit.
For FT>2, optimality among all legal K3/K4/K5 actions SHALL NOT be claimed.

#### Scenario: Additional free transfers
- **WHEN** a Decision with FT>2 is rendered
- **THEN** the UI discloses that only up to two transfers per gameweek are evaluated.

### Requirement: Experimental expansion stays isolated
K<=5 challengers SHALL remain diagnostic and disabled in production. Realised out-of-sample
decision superiority SHALL NOT be represented as established.

#### Scenario: Required adversarial failure
- **WHEN** the reduced exhaustive oracle gives290.372 and Challenger C gives282.101
- **THEN** the gap8.271 remains an integration blocker and research is deferred.

### Requirement: Production safety and lineage
V22, Decision/Chip integration, terminal FT value and Market Shadow influence=false SHALL remain
the accepted baseline. Account operations SHALL remain read-only and old reports immutable.

#### Scenario: Tooling setup
- **WHEN** developer tooling is configured
- **THEN** it does not regenerate projections, run Chip Screen, mutate accounts or rebuild EXEs.

## Purpose
Define isolated Phase1 legal-transfer generation and authorized Phase2 native V3 candidate
evaluation, with explicit surrogate/proof boundaries and no production integration.

## ADDED Requirements

### Requirement: Explicit experimental boundary
The experiment SHALL run in a separate development worker and SHALL NOT alter production
V3, GUI imports, packaging, projections, reports, Market Shadow or account state.

#### Scenario: Phase1 execution
- **WHEN** legal packages are generated
- **THEN** only `.venv-solver` imports OR-Tools and no production solver is enabled.

### Requirement: Model and native objective parity
The experiment MUST declare its universe and simultaneous roster/price/FT/hit constraints.
Each package SHALL pass canonical validation. Phase1 objective SHALL be explicitly a linear
all-roster projection surrogate, not lineup scoring or the complete V3 objective.

#### Scenario: Simultaneous atomic transfer
- **WHEN** a final package is legal but its proper sequential prefixes violate club or budget limits
- **THEN** the final package remains eligible and its native finance/roster validation must pass.

### Requirement: Separate deterministic K allocation
For each exact K0..5 the Phase1 worker SHALL generate up to five distinct final rosters using no-good cuts,
one worker, a fixed seed, zero gap limits and a bounded per-solve time. Every attempt SHALL record
status and applicable objective bound; UNKNOWN SHALL NOT be treated as a feasible result.

#### Scenario: Insufficient pool
- **WHEN** fewer legal final squads exist than the per-K allocation
- **THEN** only distinct feasible packages are returned and the final infeasible/limited attempt is recorded.

### Requirement: Restricted surrogate oracle
Reduced exhaustive tests SHALL require exact scaled-surrogate agreement for OPTIMAL results.
Frozen GW8 evaluation SHALL preserve verified lineage and investigate reference K2/K3 membership
without injecting those transfers into the generator.

#### Scenario: FT4 fifth transfer
- **WHEN** a five-transfer final package is generated with FT4
- **THEN** native validation confirms the canonical four-point hit and FT rollover.

### Requirement: Scoped optimality claims
Any optimality claim MUST include the mathematical model, solver status, objective bound, gap
settings, search scope and integer-scaling error. Approximation and assumptions SHALL be explicit.

#### Scenario: Time-limited feasible solution
- **WHEN** a time limit yields FEASIBLE with a remaining objective-bound gap
- **THEN** the report labels the solution feasible and does not claim optimality.

#### Scenario: Scaled optimum
- **WHEN** CP-SAT proves an optimum of a restricted integer model
- **THEN** the claim applies only to that model/universe unless floating-objective equivalence is proven.

### Requirement: Native Phase2 complete path evaluation
Phase2 SHALL compare A top5/K, B top10/K, C top5 plus5 structural alternatives/K for K0..5.
Every evaluated current package MUST use simultaneous native legality and the existing V3 future
search with K<=2, beam40, horizon3, lineup optimizer and terminal FT value. No production code changes.

#### Scenario: Complete objective reconstruction
- **WHEN** a candidate search returns a path
- **THEN** independent native replay confirms lineup points minus hits plus terminal FT.

### Requirement: Context isolation and incumbent protection
All shared caches SHALL bind exact PlanningContext, input integrity and configuration. Worker data
SHALL use a validated versioned JSON boundary; failures SHALL preserve the independent incumbent.

#### Scenario: Stale cache or challenger failure
- **WHEN** inputs differ or a challenger fails
- **THEN** reject reuse and retain the valid incumbent without changing production selection.

### Requirement: Bounded evidence and honest recall
GW8 SHALL run A first and B/C only within declared time/candidate budgets. Reports SHALL separate
generation, native validation, V3, cache and memory metrics and identify natural K2/K3 reference recall.

#### Scenario: Evaluation budget exhausted
- **WHEN** a deadline prevents completion
- **THEN** report PARTIAL, completed scores only, and no global multi-GW optimality claim.

### Requirement: V3 anchored neighborhoods
Phase2B SHALL use at most3 verified K2 anchors and at most12 new unique K3..5 full V3 evaluations.
Generic neighborhood cuts SHALL preserve incoming overlap and allow outgoing funding substitutions,
positional upgrades and atomic final packages. Ranking SHALL include real V3 anchor evidence and
native optimized-XI path evidence, not just the linear surrogate. Production SHALL remain unchanged.

#### Scenario: Frozen GW8 recall target
- **WHEN** a known superior K3 is tested
- **THEN** observe natural generation and selection without injecting any target names or IDs.

### Requirement: Phase2 cache integrity and bounded latency
Cached results MUST match exact context, input/configuration/artifact identities and native replay.
New full-search evaluation SHALL stop at120s and report every incomplete/missing result explicitly.

#### Scenario: Deadline or solver failure
- **WHEN** a new candidate cannot complete or CP-SAT fails
- **THEN** preserve the independent incumbent and all previously valid candidates without score regression.

### Requirement: Final neighborhood oracle evidence
The experiment SHALL report six reduced synthetic contexts, including atomic K4, FT5, constrained
funds, stronger K3 extension, disconnected K3 and dominating HOLD. Each SHALL distinguish generated
optimum, missed optimum, objective gap and cause. GO SHALL require reference recall, objective/
legality/FT parity, incumbent protection, acceptable oracle coverage, deterministic output and latency.

#### Scenario: Optimum outside anchors
- **WHEN** a legal superior package lies outside every retained incoming neighborhood
- **THEN** report its miss and gap, retain the incumbent and keep the method diagnostic-only.

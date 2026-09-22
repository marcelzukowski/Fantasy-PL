# Monte Carlo Match Simulator Specification

## 1. Purpose

The Monte Carlo Match Simulator converts probabilistic team, player, minutes and event-model outputs into coherent simulated football matches.

Its purpose is to generate realistic joint distributions of:

```text
team goals
player minutes
player goals
player assists
clean sheets
goals conceded while player is on pitch
goalkeeper saves
penalty events
defensive contributions
cards
BPS / bonus
```

The simulator is the bridge between:

```text
PREDICTIVE MODELS
```

and:

```text
FPL SCORING ENGINE
```

The simulator must preserve important dependencies between events.

It must NOT simulate each player's FPL points independently.

---

# 2. Core principle

A football match is a shared stochastic system.

Example:

If the simulation produces:

```text
Arsenal 2-0 Chelsea
```

then:

* Arsenal players collectively scored exactly 2 team goals,
* Chelsea players collectively scored 0 team goals,
* Arsenal may have a clean sheet,
* Chelsea cannot have a clean sheet,
* Arsenal goalscorers must be on the pitch when their goals occur,
* assists must correspond to compatible goals,
* goalkeeper saves must be coherent with shots on target and goals conceded,
* bonus must be determined relative to other players in the same simulated fixture.

Therefore:

```text
PLAYER EVENTS CANNOT BE SIMULATED AS INDEPENDENT Bernoulli DRAWS.
```

---

# 3. Default number of simulations

Default:

```text
10,000 simulations per fixture
```

Configuration:

```yaml
monte_carlo:
  simulations_per_fixture: 10000
```

Must be configurable.

For:

```text
development
unit tests
CI
```

smaller values may be used.

Example:

```text
100
500
1000
```

For final production projection:

```text
>= 10,000
```

unless convergence testing proves fewer simulations are sufficient.

---

# 4. Convergence testing

Do not assume 10,000 is automatically optimal.

Test stability at:

```text
1,000
2,500
5,000
10,000
25,000
50,000
```

Measure stability of:

```text
player EV
P(return)
P(10+)
captain rankings
transfer rankings
```

Select the lowest simulation count that delivers acceptable stability.

Still retain:

```text
10,000
```

as default starting value.

---

# 5. Random seed

Every simulation run must support:

```text
random_seed
```

Example:

```yaml
random_seed: 42
```

Requirements:

* fixed seed -> reproducible results,
* different seed -> independent stochastic sample,
* seed stored with simulation metadata.

---

# 6. Stable simulator input contract

For every fixture:

```text
fixture_id
prediction_timestamp

home_team_id
away_team_id

home_goal_distribution
away_goal_distribution

home_expected_goals
away_expected_goals

player_minutes_distributions

player_goal_parameters
player_assist_parameters
player_save_parameters
player_defcon_parameters
player_card_parameters

set_piece_context
penalty_context

bonus_parameters

model_version
dataset_version
feature_version
```

Optional:

```text
goal_timing_parameters
score_state_parameters
lineup_coherence_parameters
event_rate_uncertainty
```

---

# 7. Stable simulator output contract

For every simulation-player-fixture row:

```text
simulation_id
fixture_id
player_id

started
entry_minute
exit_minute
minutes

goals
assists
fpl_assists

clean_sheet_eligible
goals_conceded_while_on_pitch

saves
penalties_faced
penalties_saved

defensive_contributions

yellow_cards
red_cards

own_goals
penalties_missed

bps
bonus

simulation_seed
```

Fixture-level simulation output:

```text
simulation_id
fixture_id

home_goals
away_goals

goal_events
penalty_events
card_events

home_shots_on_target
away_shots_on_target
```

---

# 8. Simulation hierarchy

Recommended execution order:

```text
1. Sample player availability / appearance
2. Sample starting lineups
3. Sample player minutes / substitution timing
4. Sample team score
5. Sample goal timing
6. Allocate goalscorers
7. Allocate assists
8. Simulate penalties
9. Simulate goalkeeper shot/save process
10. Determine player clean-sheet eligibility
11. Simulate defensive contributions
12. Simulate cards
13. Simulate rare negative events
14. Calculate BPS
15. Allocate bonus
16. Pass complete state to FPL scoring
```

Some components may later be reordered if statistical modelling requires it.

---

# 9. Simulation of player appearance

Use Minutes Model outputs.

For each player sample:

```text
appearance
start
minutes
```

The sampled outcome must be internally consistent.

Example:

If:

```text
started = false
```

and:

```text
appeared = false
```

then:

```text
minutes = 0
```

If:

```text
started = true
```

minutes should come from:

```text
starter_minutes_distribution
```

If:

```text
started = false
appeared = true
```

minutes come from:

```text
bench_minutes_distribution
```

---

# 10. Lineup coherence

Long-term target:

Every team should have exactly:

```text
11 starting players
```

in each simulation.

Avoid situations where independent start sampling produces:

```text
9 starters
or
14 starters
```

---

# 11. Initial lineup approach

Preferred initial production approach:

For each tactical position / role group:

```text
sample starting XI jointly
```

using:

```text
P(start)
role
position
squad competition
formation probabilities
```

subject to:

```text
11 starters
valid tactical composition
```

---

# 12. Simpler fallback

If joint lineup sampling is too complex initially:

1. sample start probabilities,
2. rank sampled starter scores,
3. select most likely valid XI,
4. enforce positional/tactical constraints.

This is preferable to unrestricted independent starters.

---

# 13. Goalkeeper lineup

Exactly:

```text
1 starting goalkeeper
```

per team.

If first-choice GK unavailable:

sample among eligible alternatives.

---

# 14. Outfield lineup constraints

Do not force exact FPL positional constraints for actual football lineups.

Football lineup structure should use tactical role/formation.

Example:

```text
3 CB
2 wingbacks
2 CM
2 AM
1 ST
```

may be valid.

---

# 15. Formation sampling

Optional but recommended.

Sample:

```text
formation
```

from:

```text
formation_probability_distribution
```

provided by Tactical Context.

Then select roles compatible with that formation.

---

# 16. Formation fallback

If formation prediction is unavailable:

use:

```text
dominant_recent_formation
```

with tactical uncertainty.

---

# 17. Player substitution timing

Each sampled player should receive:

```text
entry_minute
exit_minute
```

Examples:

Starter playing 72:

```text
entry = 0
exit = 72
```

Substitute playing 24:

```text
entry = 66
exit = 90
```

Unused substitute:

```text
minutes = 0
```

---

# 18. Substitution consistency

A replaced player and substitute should be temporally compatible where possible.

Long-term:

```text
player A exits at 70
player B enters at 70
```

Initial implementation may approximate this if complete lineup/substitution simulation is too costly.

---

# 19. Player on-pitch function

Define:

```text
is_on_pitch(player, minute)
```

This function is fundamental.

Use it for:

```text
goal eligibility
assist eligibility
penalty taking
clean-sheet eligibility
goals conceded
cards
defcon exposure
```

---

# 20. Team score simulation

Use Team Strength Model outputs.

Possible approach:

```text
sample home_goals
sample away_goals
```

from:

```text
Dixon-Coles adjusted joint score distribution
```

Preferred over two completely independent Poisson samples.

---

# 21. Joint score distribution

If Dixon-Coles provides:

```text
P(home_goals = h, away_goals = a)
```

sample directly from this matrix.

Example:

```text
0-0
1-0
0-1
1-1
2-0
2-1
...
```

---

# 22. Score support

Suggested internal support:

```text
0–8 goals per team
```

with tail handling.

Very high score outcomes can be grouped or sampled from residual tail.

Ensure total probability:

```text
≈ 1
```

---

# 23. Goal timing

After score is sampled:

sample the time of each goal.

Example:

```text
home goals = 2

goal 1: minute 24
goal 2: minute 77
```

Goal times are required for:

```text
player-on-pitch eligibility
clean sheet logic
goalkeeper goals conceded
assist allocation
```

---

# 24. Goal timing baseline

Use empirical league-wide distribution.

Potential buckets:

```text
1–15
16–30
31–45+
46–60
61–75
76–90+
```

Within bucket sample exact minute.

---

# 25. Continuous timing option

Alternative:

use empirical cumulative distribution of goal times.

Sample:

```text
u ~ Uniform(0,1)
goal_minute = inverse_CDF(u)
```

Preferred when enough historical data exists.

---

# 26. Added time

Represent:

```text
45+
90+
```

consistently.

For FPL purposes, it may be sufficient to map added time into:

```text
45
90
```

or continuous effective minute.

Document chosen convention.

---

# 27. Score-state-dependent timing

Future advanced option.

Goal hazard may depend on:

```text
current score
remaining time
team strength
```

Not mandatory initially.

---

# 28. Goalscorer allocation

For every simulated team goal:

select one eligible goalscorer.

Eligibility:

```text
player belongs to scoring team
player is on pitch at goal minute
```

---

# 29. Goalscorer weights

Weight candidates using:

```text
fixture_npxg_rate
penalty role if penalty
tactical role
sampled minutes/on-pitch state
```

Conceptually:

```text
weight_i =
current goal-hazard of player i
```

Normalize:

```text
P(scorer=i)
=
weight_i / sum(weight)
```

---

# 30. Unallocated scorer probability

The dataset may not represent every possible player perfectly.

Allow:

```text
other/unmodelled player
```

probability if necessary.

However, for active PL squads the target should be near-complete allocation.

---

# 31. Goal allocation consistency

For every simulation:

```text
sum(player goals for team)
+
unallocated goals
+
opponent own goals
=
team goals
```

This must be enforced.

---

# 32. Multiple goals

The same player may score multiple times.

Do not remove a player from scorer candidates after scoring once.

---

# 33. Penalty goal classification

A goal may have type:

```text
open_play
penalty
direct_free_kick
own_goal
```

Goal type influences:

```text
assist eligibility
penalty taker
BPS
```

---

# 34. Penalty event simulation

Penalties should be simulated as shared match events.

For each team:

```text
sample penalty awarded
```

Potentially:

```text
0
1
2+
```

using appropriate low-frequency distribution.

---

# 35. Penalty taker selection

At penalty minute:

1. determine players on pitch,
2. read penalty hierarchy,
3. select highest-ranked available taker,
4. incorporate hierarchy confidence if uncertain.

---

# 36. Uncertain penalty hierarchy

Example:

```text
Player A rank 1 confidence 0.60
Player B rank 2
```

Monte Carlo may sample alternative taker scenarios according to uncertainty.

This naturally propagates penalty uncertainty into FPL EV.

---

# 37. Penalty outcome

Sample:

```text
goal
saved
missed/off-target
```

according to:

```text
penalty taker finishing
goalkeeper penalty-save skill
league priors
```

---

# 38. Penalty and team score coherence

If a penalty is scored:

it must contribute one of the already simulated team goals.

Do NOT:

```text
sample team score 2
then add penalty goal
making score 3
```

Instead either:

### Method A

Sample goal types after total team goals.

or:

### Method B

Generate scoring process first and derive total score.

Initial recommendation:

```text
sample team goal total
then classify a subset of goals as penalties
```

with calibration to historical penalty rates.

---

# 39. Assist allocation

For each eligible goal:

determine:

```text
assisted
or
unassisted
```

Penalty and own-goal cases follow season/FPL logic separately.

---

# 40. Assister selection

Candidates:

```text
same team
on pitch at goal minute
not goalscorer
```

Weights:

```text
fixture_xa_rate
set-piece role
tactical creation role
```

---

# 41. FPL assist layer

Distinguish:

```text
official_assist
```

and:

```text
fpl_assist
```

where possible.

If detailed event data does not permit exact FPL-assist reconstruction:

apply calibrated probabilistic conversion.

---

# 42. Goal/assist consistency

A single normal goal should not have:

```text
multiple FPL assists
```

unless official FPL rules change.

The scoring-rules configuration decides final attribution logic.

---

# 43. Self-assist prevention

A goalscorer cannot assist their own goal.

Always enforce:

```text
scorer_id != assister_id
```

---

# 44. Goalkeeper shot process

For each team facing opposition attack, simulate:

```text
shots_on_target_faced
```

consistent with:

```text
opponent goals
expected SOT
```

---

# 45. Save consistency

For starting goalkeeper:

```text
saves =
shots_on_target_faced
-
goals_conceded_by_goalkeeper
```

subject to edge-case event definitions.

This is preferable to independently drawing saves.

---

# 46. Shots-on-target model

Possible distribution:

```text
Poisson
negative binomial
```

with mean based on:

```text
opponent attack
team defensive strength
historical SOT rates
```

But enforce:

```text
shots_on_target_faced >= goals_conceded
```

---

# 47. Goalkeeper substitution

Rare but possible.

If goalkeeper changes during match:

goals conceded and saves must be assigned by time on pitch.

This can be handled using the same:

```text
is_on_pitch
```

logic.

---

# 48. Clean-sheet eligibility

For every player:

track whether their team conceded while they were on the pitch.

Required:

```text
goals_conceded_while_on_pitch
```

Then FPL Scoring Engine applies season-specific CS rules.

---

# 49. Example clean-sheet simulation

Simulation:

```text
Defender exits minute 70
Opponent scores minute 82
```

Then:

```text
goals_conceded_while_on_pitch = 0
```

The scoring engine decides whether the player earns clean-sheet points based on minutes threshold.

---

# 50. Defender enters after goal

Example:

```text
Opponent scores minute 20
Defender enters minute 60
No further goals
```

For the player's on-pitch interval:

```text
goals_conceded_while_on_pitch = 0
```

Scoring rules determine whether sufficient minutes were played.

---

# 51. Goals conceded deduction

For GK/DEF:

negative points for goals conceded depend on goals conceded while the player is on pitch.

Therefore store:

```text
goals_conceded_while_on_pitch
```

not only final match score.

---

# 52. Defensive contribution simulation

For each player:

sample defensive-action total conditional on:

```text
sampled minutes
tactical role
opponent possession
opponent attacking volume
team defensive style
fixture_defcon_rate
```

Potential distributions:

```text
Poisson
negative binomial
```

---

# 53. Overdispersion

Defensive events and saves may be more variable than Poisson.

Test:

```text
variance > mean
```

If strong overdispersion exists:

prefer:

```text
negative binomial
```

---

# 54. Defensive-event coherence

Future advanced model may simulate:

```text
tackles
interceptions
clearances
blocks
recoveries
```

separately.

Initial implementation may simulate:

```text
aggregate FPL-relevant defensive contributions
```

if season scoring allows it.

---

# 55. Card simulation

For every appearing player:

sample:

```text
yellow card
red card
```

conditional on:

```text
minutes
role
historical rate
fixture context
```

---

# 56. Red-card timing

If red card occurs:

sample minute.

Then:

```text
player exit_minute = red_card_minute
```

This affects:

```text
minutes
goal eligibility
assist eligibility
clean-sheet exposure
defensive contributions
```

---

# 57. Second-yellow interaction

Optional advanced logic.

If second yellow leads to red:

avoid impossible:

```text
yellow + independent straight red
```

double counting.

---

# 58. Team player count after red

Advanced simulation may account for:

```text
10-player team effects
```

on goal rates.

Not mandatory initially.

First production version may retain original team score distribution.

---

# 59. Own-goal simulation

Sample rare own goals using:

```text
position prior
minutes
historical rate
```

If own goal occurs:

it contributes to opponent team score.

Therefore must be incorporated into team score accounting.

---

# 60. Recommended own-goal simplification

Because own goals are rare:

after team score is sampled, classify a small share of goals as:

```text
opponent own goal
```

rather than generating extra goals.

---

# 61. BPS simulation

After major football events are known:

calculate/simulate BPS components.

Potential components:

```text
minutes
goals
assists
clean sheets
saves
cards
penalty events
defensive actions
pass completion
big chances missed
errors
```

according to available data and season rules.

---

# 62. BPS baseline

If full BPS reconstruction is unavailable:

use calibrated model:

```text
historical_base_BPS_per_minute
+
simulated_event_adjustments
```

Then obtain:

```text
simulated_bps
```

for every player.

---

# 63. Bonus allocation

Within each simulated fixture:

rank players by:

```text
BPS
```

Apply official FPL bonus allocation rules.

Output:

```text
0
1
2
3
```

or season-specific values.

---

# 64. Bonus tie rules

Implement exact season-specific tie handling through configuration.

Do not approximate ties by randomly breaking them unless official rules require that.

---

# 65. Player absence and BPS

Players with:

```text
0 minutes
```

must not receive bonus.

---

# 66. Correlation structure

The simulator must preserve at least these correlations:

```text
team goals ↔ player goals
team goals ↔ player assists
opponent goals ↔ clean sheets
opponent SOT ↔ goalkeeper saves
goals ↔ BPS/bonus
assists ↔ BPS/bonus
minutes ↔ all player events
penalty events ↔ penalty taker outcomes
```

---

# 67. Negative correlations

Important examples:

```text
more opponent goals
→ lower clean sheet probability
```

and:

```text
one player receiving a team goal
→ slightly reduces remaining team-goal allocation to teammates
```

These emerge naturally from shared-event simulation.

---

# 68. Positive correlations

Examples:

```text
high-scoring match
→ more goals and assists across players
```

```text
team clean sheet
→ multiple defenders receive CS opportunity simultaneously
```

This is why independent player-point simulation is wrong.

---

# 69. Player-event uncertainty

The simulator should optionally sample uncertain rate parameters.

Example:

```text
true_fixture_npxg_rate
~
distribution around estimated rate
```

Then sample goals conditional on that rate.

This represents model uncertainty in addition to football randomness.

---

# 70. Aleatoric uncertainty

Football randomness:

```text
same true rates
different match outcome
```

Handled through normal Monte Carlo event sampling.

---

# 71. Epistemic uncertainty

Model uncertainty:

```text
we are uncertain what the true rate actually is
```

Handled through parameter sampling.

---

# 72. Recommended uncertainty architecture

Each major predictive module may provide:

```text
point estimate
uncertainty parameter
```

Simulation:

```text
sample latent rate
↓
sample match outcome
```

---

# 73. New player example

Player:

```text
xG rate estimate = 0.50
high uncertainty
```

Simulation should explore a wider range of plausible true rates than for an established player with identical point estimate.

---

# 74. Team-strength uncertainty

Likewise:

```text
newly promoted team
new manager
```

should have wider:

```text
expected-goals uncertainty
```

This should propagate into:

```text
goal distributions
clean-sheet probabilities
player EV
```

---

# 75. Sensitivity versus Monte Carlo uncertainty

Do not confuse:

```text
normal simulation uncertainty
```

with:

```text
decision sensitivity analysis
```

Monte Carlo produces the expected outcome distribution given current model beliefs.

Sensitivity Engine later asks:

```text
What if our beliefs themselves are wrong within reasonable ranges?
```

Both are required.

---

# 76. Simulation result storage

Do NOT necessarily persist all:

```text
10,000 × every player × every fixture
```

rows permanently.

This can become large.

Recommended:

```text
temporary simulation table
↓
aggregate
↓
persist summary distributions
```

Persist full simulation samples only when:

```text
debugging
model research
specific analysis
```

---

# 77. DuckDB / Parquet

Recommended implementation:

```text
simulation output
→ in-memory / Arrow
→ DuckDB aggregation
→ Parquet summaries
```

Avoid sending raw simulation rows to an LLM.

---

# 78. Aggregated player outputs

After simulations calculate:

```text
mean
median
standard deviation
quantiles
```

and probabilities:

```text
P(blank)
P(return)
P(5+)
P(8+)
P(10+)
P(15+)
```

after FPL scoring.

---

# 79. Quantiles

Recommended:

```text
p10
p25
p50
p75
p90
```

for player FPL point distributions.

These help understand floor/upside.

---

# 80. Skewed distributions

FPL points are highly skewed.

Therefore:

```text
mean != median
```

is common.

Always retain at least:

```text
mean
median
```

---

# 81. Captain simulation

Do not need a separate football simulation.

Captain scoring is derived later:

```text
captain FPL points multiplier
```

applied to the same player simulation samples.

This preserves haul variance correctly.

---

# 82. Triple Captain

Same principle.

Do not simulate player again.

Apply chip scoring multiplier downstream.

---

# 83. Bench Boost

Again:

same player simulations.

Optimizer/scoring decides whether bench scores count.

---

# 84. Double Gameweeks

For each fixture in DGW:

simulate separately.

Then for each player and simulation scenario:

```text
GW points =
fixture_1 points
+
fixture_2 points
```

---

# 85. DGW minutes dependency

Minutes in two fixtures may be correlated due to:

```text
rotation
fatigue
```

Long-term target:

simulate multi-fixture minutes jointly.

Example:

```text
starts first fixture
→ potentially reduced start probability second fixture
```

---

# 86. Initial DGW approach

First production version may simulate fixtures independently using fixture-specific xMins that already includes congestion.

Document this approximation.

---

# 87. Future multi-fixture simulation

Advanced:

```text
GW-level player state
↓
fixture 1 minutes
↓
fatigue / rotation state
↓
fixture 2 minutes
```

Only add if backtests justify complexity.

---

# 88. Blank Gameweeks

No fixture means:

```text
0 football-event points
```

for that player in that GW.

No Monte Carlo fixture required.

---

# 89. Postponed fixtures

Simulate only fixtures known to be scheduled at:

```text
prediction_timestamp
```

If postponement was not known yet historically:

historical backtest must use the schedule known at that time.

---

# 90. Fixture independence

Different fixtures are often simulated independently.

However, shared squad/minutes constraints across close fixtures may create dependency.

Initial architecture may ignore cross-fixture correlation except through precomputed xMins.

---

# 91. Simulation performance target

10,000 simulations across all PL fixtures should be computationally practical.

Avoid Python loops such as:

```text
for simulation
  for player
    for event
```

where vectorization is possible.

Prefer:

```text
NumPy
Polars
PyArrow
DuckDB
```

for bulk operations.

---

# 92. Vectorization

Example:

Instead of sampling one player at a time:

```text
np.random...
```

generate arrays:

```text
shape = (n_simulations, n_players)
```

where appropriate.

---

# 93. Memory management

Do not create huge unnecessary dense tensors.

Use:

```text
fixture-level batches
```

Example:

```text
simulate one fixture
aggregate
release intermediate arrays
```

This is sufficient for FPL.

---

# 94. Parallelism

Fixtures may be simulated in parallel.

Possible:

```text
multiprocessing
joblib
Ray optional
```

Do not introduce distributed infrastructure unless required.

Simple multiprocessing should be enough initially.

---

# 95. Deterministic parallel seeds

If parallelizing:

derive fixture seeds deterministically.

Example:

```text
fixture_seed =
hash(global_seed, fixture_id)
```

This preserves reproducibility independent of execution order.

---

# 96. Simulation metadata

Persist:

```text
simulation_run_id
prediction_timestamp
simulation_count
global_seed

team_model_version
minutes_model_version
talent_model_version
event_model_version

dataset_version
feature_version

started_at
completed_at
```

---

# 97. Simulation run ID

Use stable unique identifier.

Example:

```text
sim_2026_09_10_gw4_v001
```

or UUID/ULID.

---

# 98. Validation against historical distributions

The simulator itself must be backtested.

Compare simulated versus realized:

```text
scorelines
goal totals
clean sheets
player goals
player assists
save counts
card counts
bonus distributions
```

---

# 99. Scoreline validation

Compare:

```text
simulated P(0-0)
simulated P(1-0)
simulated P(1-1)
...
```

with actual historical frequencies in equivalent prediction buckets.

---

# 100. Total goals calibration

Group fixtures by simulated:

```text
expected_total_goals
```

Check realized total goals.

---

# 101. Clean-sheet calibration

If simulation gives:

```text
40% CS
```

teams should keep clean sheets approximately 40% of the time across large samples.

---

# 102. Player goal calibration

For players with:

```text
P(goal) ~ 0.30
```

actual scoring rate should approach 30%.

---

# 103. Player assist calibration

Same for:

```text
P(assist)
```

---

# 104. Save calibration

Compare:

```text
simulated save distribution
```

to actual saves.

Especially:

```text
P(3+)
P(6+)
```

---

# 105. Bonus calibration

Compare:

```text
simulated expected bonus
```

and:

```text
P(any bonus)
```

with historical outcomes.

---

# 106. Joint calibration

Important:

Do not validate only marginal distributions.

Also test correlations.

Examples:

```text
correlation(team goals, player goals)
correlation(team CS, defender points)
correlation(saves, goals conceded)
correlation(goals, bonus)
```

---

# 107. Correlation diagnostic

Maintain:

```text
event_correlation_diagnostics
```

for simulated data.

Compare against historical correlation matrices where possible.

---

# 108. Impossible-state tests

Automated tests must reject impossible states.

Examples:

```text
player scores while not on pitch
player assists while not on pitch
player assists own goal
team has 0 goals but player has 1 goal
GK saves < 0
shots on target < goals
clean-sheet player conceded while on pitch
suspended player plays
```

---

# 109. Probability-sum tests

Ensure all categorical distributions sum to approximately:

```text
1.0
```

with numerical tolerance.

---

# 110. Determinism test

Given identical:

```text
inputs
seed
version
```

simulation output must be identical.

---

# 111. Seed-variance test

Different seeds should produce slightly different sample estimates but converge around similar EV.

---

# 112. Simulation-count stability test

Run:

```text
5k
10k
25k
```

and verify top player rankings do not change excessively due purely to Monte Carlo noise.

---

# 113. Extreme scenario tests

Test:

```text
expected goals = near 0
expected goals = very high
player P(start) = 0
player P(start) = 1
P(CS) near 0
P(CS) near 1
```

System must remain numerically stable.

---

# 114. Missing-data behavior

If optional event rate unavailable:

use fallback model before simulation.

Simulator itself should receive a valid canonical distribution.

Do not make simulator responsible for arbitrary provider fallbacks.

---

# 115. Failure policy

If critical simulation input is missing:

fail explicitly.

Example:

```text
no team goal distribution
```

should not silently become:

```text
0 goals
```

---

# 116. Logging

Record warnings such as:

```text
goal allocation required unmodelled-player fallback
lineup could not satisfy tactical constraints
BPS fallback model used
penalty hierarchy low confidence
```

---

# 117. Simulation quality flags

Potential output:

```text
simulation_quality:
    high
    medium
    low
```

based on:

```text
input completeness
model uncertainty
fallback usage
lineup coherence
```

---

# 118. Graceful approximation hierarchy

Preferred:

```text
full coherent model
```

Fallback:

```text
team-score coherent
+
player goal/assist allocation
+
minutes
```

Minimum acceptable:

```text
team score + player rates + minutes
```

Never fall back to completely independent player FPL-point sampling as the main system.

---

# 119. Simulation modes

Support:

```text
fast
standard
research
```

Example:

```yaml
fast:
  simulations: 1000
  epistemic_sampling: false

standard:
  simulations: 10000
  epistemic_sampling: true

research:
  simulations: 50000
  persist_raw_samples: true
```

---

# 120. Production default

Recommended:

```text
mode = standard
```

---

# 121. Debug mode

Allow simulation of:

```text
one fixture
one player
fixed scoreline
fixed lineup
```

for debugging.

Example:

```text
force score = 2-1
```

then inspect goal allocation and scoring.

---

# 122. Event trace

Optional debug output for one simulation:

```text
23' Player A goal, Player B assist
61' Player C yellow
70' Player D off
82' Opponent goal
```

This is extremely useful for validating scoring logic.

---

# 123. No LLM in simulation loop

The simulator must be entirely deterministic/statistical code.

Do NOT use an LLM to:

```text
select scorer
decide assist
generate result
```

LLM may later explain aggregated simulation results.

---

# 124. Interaction with FPL Scoring Engine

Simulator outputs:

```text
football state
```

Scoring Engine outputs:

```text
FPL points
```

Do not mix responsibilities.

---

# 125. Interaction with Projection Engine

After scoring:

aggregate simulations into:

```text
expected points
median
probabilities
quantiles
```

Projection Engine handles:

```text
1 GW
3 GW
6 GW
```

aggregation.

---

# 126. Interaction with Optimizer

Optimizer should generally consume:

```text
aggregated simulation distributions
```

not millions of raw rows.

Potential inputs:

```text
EV
variance
quantiles
haul probabilities
```

---

# 127. Joint player samples for optimizer

For advanced risk-aware optimization:

retain aligned simulation scenarios across players.

Why:

Player outcomes are correlated.

Example:

Two Arsenal attackers may both benefit in a high-scoring Arsenal scenario.

This can matter for:

```text
portfolio-style squad risk
captaincy
```

---

# 128. Initial optimizer integration

Initial optimizer may consume:

```text
expected values
```

plus selected risk metrics.

Joint scenario optimization can be added later if justified.

---

# 129. Captaincy distribution

Monte Carlo enables direct comparison:

```text
Player A:
EV = 7.1
P(15+) = 16%

Player B:
EV = 6.8
P(15+) = 23%
```

This may be useful for risk-aware captaincy.

---

# 130. Floor and ceiling

Derived from simulations.

Possible reporting:

```text
floor:
p25

median:
p50

ceiling:
p90
```

Do not claim these are guaranteed outcomes.

---

# 131. Simulation bias monitoring

After each completed GW:

compare:

```text
predicted distributions
actual outcomes
```

Track systematic bias.

Example:

```text
overpredicting clean sheets
underpredicting goalkeeper saves
```

---

# 132. Drift monitoring

If event distributions shift over time:

flag model drift.

Possible signals:

```text
league scoring rate changes
new FPL rules
tactical league trends
```

---

# 133. Season change

New season:

reset or update:

```text
league priors
scoring config
team identities
promoted teams
```

Do not reset stable player identities.

---

# 134. Historical replay

Simulation must support:

```text
historical_backtest mode
```

Given a historical prediction timestamp:

reconstruct all inputs and simulate as if the future were unknown.

---

# 135. No hindsight

Historical simulation must not know:

```text
actual lineup
actual score
actual goalscorer
actual injury later that day
```

unless known before the historical prediction timestamp.

---

# 136. Performance benchmark

Recommended initial goal:

Full Premier League GW:

```text
10 fixtures
~300 relevant players
10,000 simulations each
```

should run comfortably on a normal developer machine.

Do not optimize prematurely before profiling.

---

# 137. Profiling

Measure:

```text
lineup sampling time
score sampling time
goal allocation time
assist allocation time
BPS time
aggregation time
```

Optimize actual bottlenecks.

---

# 138. Numerical precision

Use:

```text
float32
```

where adequate for large simulation arrays.

Use:

```text
float64
```

for probability aggregation when numerical stability requires.

---

# 139. Probability clipping

Model outputs may produce numerical values like:

```text
1.0000001
-0.0000001
```

due to floating-point operations.

Clip safely into:

```text
[0, 1]
```

only for numerical tolerance.

Do not hide genuine invalid probabilities.

---

# 140. Probability normalization

After transformations:

normalize probability vectors explicitly.

Log when correction exceeds configured tolerance.

---

# 141. Monte Carlo error

Estimate standard error of key outputs.

For binary probability:

```text
SE ≈ sqrt(p(1-p)/N)
```

This helps determine whether simulation count is sufficient.

---

# 142. EV Monte Carlo error

For player points:

estimate:

```text
SE(mean) = std(points) / sqrt(N)
```

Optionally expose for diagnostics.

---

# 143. Simulation convergence criterion

Potential production criterion:

```text
Monte Carlo SE for expected points
< configured threshold
```

Example candidate:

```text
0.05 FPL points
```

Do not hardcode until tested.

---

# 144. Adaptive simulation count

Optional future optimization:

Start with:

```text
5,000
```

Then add simulations until:

```text
EV SE
haul probability SE
```

meet thresholds.

May reduce runtime.

Not mandatory initially.

---

# 145. Simulation caching

If inputs are identical:

cache simulation aggregation based on:

```text
fixture_id
prediction_timestamp
model versions
input hash
seed
simulation count
```

---

# 146. Input hash

Create deterministic hash of:

```text
team distributions
player distributions
context
model versions
```

to detect stale simulation output.

---

# 147. Invalid cache prevention

Any change in:

```text
xMins
team xG
player event rates
set-piece hierarchy
model version
```

must invalidate affected fixture simulation cache.

---

# 148. Fixture-level invalidation

Do not rerun every PL fixture if only one fixture's input changed.

Example:

Late Arsenal injury:

rerun only:

```text
Arsenal fixture
```

then recompute downstream GW aggregation.

---

# 149. Incremental architecture

Pipeline:

```text
changed data
↓
affected models
↓
affected fixtures
↓
rerun simulations
↓
reaggregate projections
```

This saves computation and API calls.

---

# 150. Simulation configuration file

Keep parameters external.

Potential config:

```yaml
simulations_per_fixture: 10000
random_seed: 42

goal_timing:
  enabled: true

epistemic_uncertainty:
  enabled: true

lineup_coherence:
  enabled: true

persist_raw_samples:
  enabled: false
```

Do not hardcode these values throughout Python files.

---

# 151. Versioning

Simulation logic must have:

```text
simulation_engine_version
```

Separate from predictive model versions.

Reason:

changing simulation correlations can change projections even if model inputs remain identical.

---

# 152. Comparison between simulator versions

When simulation logic changes:

run historical backtests comparing:

```text
old simulator
new simulator
```

Do not assume more realism automatically improves FPL prediction.

---

# 153. Experiment sequence

Recommended:

## SIM-001

Independent minutes sampling.

## SIM-002

Joint team score sampling.

## SIM-003

Player goalscorer allocation.

## SIM-004

Assist allocation.

## SIM-005

Goal timing.

## SIM-006

Player clean-sheet eligibility.

## SIM-007

GK shots/save coherence.

## SIM-008

Penalty events.

## SIM-009

Defensive contributions.

## SIM-010

Cards.

## SIM-011

BPS and bonus ranking.

## SIM-012

Joint lineup coherence.

## SIM-013

Epistemic parameter sampling.

## SIM-014

Simulation convergence optimization.

---

# 154. Required unit tests

At minimum:

```text
test_reproducibility_same_seed
test_different_seed_changes_samples

test_exactly_one_starting_goalkeeper
test_starting_lineup_size

test_scorer_is_on_pitch
test_assister_is_on_pitch
test_scorer_cannot_assist_self

test_player_goals_equal_team_goal_allocation
test_zero_team_goals_means_zero_player_goals

test_saves_non_negative
test_sot_not_less_than_goals

test_suspended_player_zero_minutes

test_clean_sheet_goal_timing_logic
test_goals_conceded_on_pitch

test_bonus_allocation_rules

test_probability_normalization
```

---

# 155. Required integration tests

Test complete fixture scenarios such as:

```text
0-0
1-0
2-2
4-0
```

and ensure:

```text
goals
assists
CS
saves
bonus
```

remain coherent.

---

# 156. Golden fixture test

Create a deterministic handcrafted fixture:

```text
fixed lineup
fixed score
fixed events
```

Expected outputs are manually known.

Use this to verify simulator → scoring integration.

---

# 157. Stress testing

Run thousands of simulated fixtures and assert there are no:

```text
negative minutes
minutes > allowed range
negative saves
invalid probabilities
scorers off pitch
impossible bonus allocations
```

---

# 158. Monitoring outputs

Per simulation run record:

```text
unallocated_goal_rate
lineup_constraint_failure_rate
fallback_usage_rate
average simulation runtime
Monte Carlo SE
```

---

# 159. Warning thresholds

Potential warnings:

```text
unallocated goals > 2%
lineup failure > 0.1%
simulation EV SE too high
```

Final thresholds should be configured after experimentation.

---

# 160. Acceptance criteria

The Monte Carlo Simulator is accepted when:

1. team scorelines come from calibrated team distributions,
2. player goals are coherent with team goals,
3. goalscorers are on the pitch,
4. assists are tied to compatible goals,
5. clean sheets depend on shared opponent scoring events,
6. player CS eligibility respects on-pitch timing,
7. saves are coherent with shots on target and goals conceded,
8. penalty events respect on-pitch penalty hierarchy,
9. defensive contributions depend on minutes and fixture context,
10. cards affect playing time when relevant,
11. BPS/bonus is fixture-relative,
12. simulations are reproducible with a fixed seed,
13. outputs remain stable at production simulation count,
14. impossible states are covered by automated tests,
15. historical simulation is point-in-time safe,
16. simulation can run without paid data,
17. scoring rules remain outside the simulator,
18. raw simulation data does not need to be sent to the LLM.

---

# 161. Codex implementation guidance

DO:

* start with deterministic contracts,
* create small simulation components,
* use fixture-level batches,
* vectorize where practical,
* preserve shared match events,
* write impossible-state tests,
* use deterministic random seeds,
* separate simulation from FPL scoring,
* keep configuration external,
* benchmark convergence,
* log fallback usage.

DO NOT:

* independently simulate final FPL points for each player,
* independently simulate player goals without team-total coherence,
* assign goals/assists to players not on pitch,
* calculate player clean sheets only from final score,
* simulate saves independently from goals/SOT,
* use an LLM inside the simulation loop,
* persist enormous raw simulation tables without reason,
* introduce distributed infrastructure before profiling,
* hide missing critical inputs with zeros.

---

# 162. Final principle

The Monte Carlo Simulator should answer:

```text
IF WE PLAYED THIS FIXTURE THOUSANDS OF TIMES
UNDER OUR CURRENT BELIEFS,

WHAT COMPLETE, INTERNALLY CONSISTENT
FOOTBALL OUTCOMES WOULD OCCUR?
```

Those simulated worlds must preserve:

```text
MATCH STRUCTURE
PLAYER MINUTES
EVENT DEPENDENCIES
SHARED TEAM OUTCOMES
UNCERTAINTY
```

Only after each simulated football world is complete should the system calculate:

```text
FPL POINTS.
```

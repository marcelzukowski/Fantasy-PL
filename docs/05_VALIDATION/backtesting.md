# Backtesting Specification

## 1. Purpose

Backtesting is the validation backbone of the FPL Prediction & Decision Engine.

The system must not be considered successful because:

* the architecture is sophisticated,
* predictions look reasonable,
* individual historical examples look good,
* a model has high in-sample accuracy,
* one recommended transfer happened to haul.

The system is accepted only if it demonstrates:

```text
REPRODUCIBLE
POINT-IN-TIME SAFE
OUT-OF-SAMPLE
PERFORMANCE
```

across historical Fantasy Premier League periods.

---

# 2. Primary objective

The purpose of backtesting is to answer:

```text
IF THIS SYSTEM HAD EXISTED AT THAT HISTORICAL FPL DEADLINE,
USING ONLY INFORMATION AVAILABLE AT THAT TIME,
WHAT WOULD IT HAVE PREDICTED AND RECOMMENDED?
```

Then compare those predictions and recommendations with what happened afterwards.

---

# 3. Critical no-hindsight principle

For historical prediction timestamp `T`:

```text
feature_information_time <= T
```

must always hold.

Anything learned after `T` is forbidden as an input.

This rule applies to:

```text
prices
ownership
injuries
player news
lineups
formations
transfers
managers
fixtures
bookmaker odds
xG
xA
minutes
set pieces
squad roles
FPL status
```

---

# 4. Historical prediction timestamp

Every backtest observation must explicitly define:

```text
prediction_timestamp
```

Default FPL backtesting mode:

```text
prediction_timestamp =
historical FPL deadline
```

Optionally, a configurable offset before deadline may be used.

Example:

```text
deadline - 1 hour
deadline - 6 hours
deadline - 24 hours
```

but it must be consistent within an experiment.

---

# 5. Preferred historical snapshot

For any point-in-time source:

use:

```text
latest_snapshot_strictly_before_prediction_timestamp
```

Never:

```text
nearest snapshot
```

because the nearest snapshot may occur after the deadline.

---

# 6. Missing historical information

If no valid pre-deadline snapshot exists:

preferred behavior:

```text
NULL / unavailable
```

rather than:

```text
use the next available future snapshot
```

Coverage loss is preferable to leakage.

---

# 7. Backtesting hierarchy

Validation should exist at four levels:

```text
LEVEL 1
Individual predictive models

LEVEL 2
Match simulation and FPL scoring

LEVEL 3
Player projections

LEVEL 4
Optimizer / decision strategy
```

A strong optimizer cannot compensate for badly calibrated underlying predictions indefinitely.

---

# 8. Component backtesting

Every major predictive module must be evaluated independently.

Required modules:

```text
Team Strength
Minutes
Player Talent
Tactical Context
Goals
Assists
Clean Sheets
Saves
Defensive Contributions
Cards
Bonus
```

---

# 9. End-to-end backtesting

The complete pipeline must also be evaluated:

```text
historical data
↓
historical features
↓
historical model predictions
↓
Monte Carlo
↓
historical scoring rules
↓
player projections
↓
optimizer
↓
historical decision
```

---

# 10. Walk-forward validation

Primary validation method:

```text
WALK-FORWARD
```

Example:

```text
train through GW10
predict GW11

train through GW11
predict GW12

train through GW12
predict GW13
```

The model may either:

```text
retrain each step
```

or:

```text
follow the exact production retraining schedule
```

---

# 11. Random split forbidden

Do not use ordinary random:

```text
train_test_split
```

across player-match or team-match observations for final model evaluation.

Random splitting can allow:

```text
future player form
future team strength
future manager regime
```

to influence earlier samples indirectly.

---

# 12. Time-series validation

Hyperparameter tuning must also use temporal validation.

Possible structure:

```text
TRAIN
season A through date X

VALIDATION
next N Gameweeks

TEST
later untouched Gameweeks
```

---

# 13. Final holdout

Keep at least one sufficiently recent period untouched during major model development.

Example conceptual structure:

```text
development:
older seasons

validation:
next season

final holdout:
most recent completed season
```

Exact seasons depend on data availability.

---

# 14. Never tune on final holdout

Do not repeatedly:

```text
run model
check final holdout
adjust model
run again
```

because the holdout gradually becomes training information.

---

# 15. Season-level generalization

Required experiment:

```text
train on previous seasons
test on completely unseen season
```

This tests whether the model generalizes across:

```text
new managers
new players
promoted teams
new tactical trends
```

---

# 16. Rolling historical window

Candidate approaches:

```text
all available history with decay
last 1 season
last 2 seasons
last 3 seasons
```

Compare through backtesting.

Do not assume more history always helps.

---

# 17. Expanding window

Preferred baseline:

```text
all valid history before T
```

with:

```text
time decay
```

rather than deleting older data arbitrarily.

---

# 18. Dataset versioning

Every backtest must store:

```text
dataset_version
```

Historical results must be reproducible even if upstream datasets later change.

---

# 19. Feature versioning

Every backtest must store:

```text
feature_version
```

If feature engineering changes:

run a new experiment rather than silently replacing old results.

---

# 20. Model versioning

Every prediction row must identify:

```text
model_name
model_version
training_cutoff
```

---

# 21. Simulation versioning

Store:

```text
simulation_engine_version
simulation_count
random_seed
```

---

# 22. Scoring rules version

Historical player points must be evaluated under:

```text
rules applicable to that historical season
```

Never automatically rescore all past seasons using current FPL rules.

---

# 23. Optimizer rules version

Likewise:

```text
transfer rules
chip rules
squad rules
```

must match the relevant historical season.

---

# 24. Historical data reconstruction

For each target GW reconstruct:

```text
players known at deadline
teams
prices
ownership
player status
news
fixtures known
manager state
tactical context
injury information
```

as of the historical deadline.

---

# 25. Current-season aggregate leakage

Forbidden:

```text
final season total xG
final season minutes
final season starts
final season ownership
```

for prediction earlier in that same season.

Use:

```text
season-to-date as of prediction time
```

only.

---

# 26. Rolling feature rule

For target fixture `F`:

rolling features may contain only:

```text
completed fixtures before prediction_timestamp
```

Target fixture is never part of its own feature history.

---

# 27. Future fixture leakage

A future fixture may be used only if:

```text
it was already scheduled/known
```

at historical prediction time.

Later rescheduling knowledge is forbidden.

---

# 28. Fixture congestion leakage

Feature such as:

```text
matches_next_7_days
```

may use only matches that were known/scheduled at prediction timestamp.

---

# 29. Transfer leakage

If player transfer occurs after historical deadline:

the model must not know it.

Use temporal:

```text
player_team_spell
```

tables.

---

# 30. Manager leakage

If manager is appointed after historical deadline:

do not use the new manager.

Historical team state remains under the manager/context known at the deadline.

---

# 31. Injury leakage

A player injured during training after deadline must not be marked injured in the historical pre-deadline prediction.

---

# 32. Lineup leakage

Actual target-match starting lineup is always forbidden in normal FPL pre-deadline backtesting.

It is a target/outcome.

---

# 33. Bookmaker leakage

Allowed:

```text
opening odds
odds timestamped before prediction_timestamp
```

Forbidden:

```text
closing odds after deadline
```

---

# 34. Historical FPL xP

Historical official or archived:

```text
expected_points / xP
```

must be excluded by default.

It may only be used if proven to represent the exact pre-deadline value available at the relevant timestamp.

---

# 35. Raw data immutability

Backtesting must operate from:

```text
immutable raw snapshots
```

not mutable reconstructed provider responses.

---

# 36. Backtest prediction table

Recommended canonical output:

```text
prediction_timestamp
target_gameweek

player_id
fixture_id

p_start
expected_minutes

expected_goals
expected_assists
clean_sheet_probability
expected_saves
expected_defcon
expected_bonus

expected_points
median_points

p_blank
p_return
p_5_plus
p_8_plus
p_10_plus
p_15_plus

actual_minutes
actual_goals
actual_assists
actual_points

model_versions
dataset_version
feature_version
```

---

# 37. Team Strength validation

Evaluate:

```text
expected goals
score distributions
clean sheets
```

Required metrics:

```text
Poisson deviance
negative log likelihood
MAE goals
Brier clean sheet
calibration error
```

---

# 38. Team Strength baselines

Required:

```text
league average
rolling goals
rolling xG
simple Poisson
```

Advanced model must demonstrate value over these.

---

# 39. Minutes validation

Evaluate:

```text
P(start)
expected minutes
P(60+)
P(75+)
P(90)
```

Required:

```text
MAE minutes
Brier P(start)
Brier P(60+)
Brier P(90)
log loss
calibration
```

---

# 40. Minutes baselines

Required:

```text
previous-match minutes
last-5 average minutes
last-5 start rate
```

---

# 41. Minutes segmentation

Report performance separately for:

```text
GK
DEF
MID
FWD
```

and:

```text
regular starters
rotation players
injury returns
new signings
new manager periods
```

---

# 42. Player Talent validation

Player Talent should be evaluated against future underlying performance, not one-match FPL points.

Targets:

```text
future npxG/90
future xA/90
future shots/90
future box touches/90
```

---

# 43. Talent horizons

Evaluate future rates over:

```text
next 3 matches
next 5 matches
next 10 matches
```

subject to sufficient minutes.

---

# 44. Talent transfer subset

Create dedicated subset:

```text
players changing clubs
```

Compare:

```text
raw previous-club per90
vs
context-adjusted talent model
```

---

# 45. Cross-league subset

Evaluate separately:

```text
Championship -> PL
Bundesliga -> PL
La Liga -> PL
Serie A -> PL
Ligue 1 -> PL
other -> PL
```

where sample size permits.

---

# 46. Tactical Context validation

Evaluate direct tasks such as:

```text
next known tactical role
next formation
set-piece role
```

where labels are available.

But the most important test is downstream:

```text
does tactical context improve
minutes
xG/xA
FPL projection
```

---

# 47. Regime-change subsets

Evaluate separately around:

```text
manager changes
club transfers
formation changes
role changes
injury returns
```

---

# 48. Goal Model validation

Required:

```text
Brier P(goal)
log loss
Poisson deviance
calibration
```

---

# 49. Assist Model validation

Required:

```text
Brier P(assist)
log loss
calibration
```

---

# 50. Clean Sheet validation

Required:

```text
Brier score
log loss
calibration
```

Evaluate:

```text
team CS
player CS
```

separately.

---

# 51. Save Model validation

Required:

```text
MAE saves
Poisson/negative-binomial deviance
Brier P(3+ saves)
Brier P(6+ saves)
```

---

# 52. Defensive Contribution validation

Required:

```text
MAE action count
Brier threshold reached
calibration
```

---

# 53. Card Model validation

Required:

```text
Brier yellow
Brier red
log loss
```

Red-card metrics must be interpreted cautiously because the event is rare.

---

# 54. Bonus validation

Required:

```text
MAE bonus
Brier any bonus
Brier 3 bonus
BPS ranking accuracy
```

---

# 55. Simulation validation

Monte Carlo must be evaluated against historical distributions.

Compare:

```text
scoreline distribution
goal totals
clean sheets
goalkeeper saves
cards
bonus
```

---

# 56. Marginal calibration

Check individual probabilities:

```text
P(goal)
P(assist)
P(CS)
P(start)
P(60+)
```

---

# 57. Joint calibration

Also check correlations:

```text
team goals ↔ player goals
team goals ↔ assists
team CS ↔ defender FPL points
opponent shots ↔ GK saves
goals ↔ bonus
```

---

# 58. Player FPL expected-points validation

For player projections compare:

```text
expected_points
```

with realized FPL points over large samples.

Metrics:

```text
MAE
RMSE
mean bias
Spearman rank correlation
```

However, MAE alone is insufficient because FPL scoring is highly stochastic.

---

# 59. Expected value calibration

Bucket players by predicted EV.

Example:

```text
2.0-2.9
3.0-3.9
4.0-4.9
5.0-5.9
6.0+
```

Compare:

```text
mean predicted points
mean realized points
```

---

# 60. Probability calibration

For:

```text
P(return)
P(10+)
P(15+)
```

bucket predictions and compare realized frequencies.

---

# 61. Rank validation

FPL decisions often depend more on ranking players than exact EV.

Required:

```text
Spearman rank correlation
```

between:

```text
predicted EV
```

and:

```text
future realized performance
```

over meaningful horizons.

---

# 62. Top-player precision

Evaluate:

```text
top 5
top 10
top 20
```

predicted players by position.

Measure future performance versus population.

---

# 63. Position-specific projections

Report FPL projection metrics separately for:

```text
GK
DEF
MID
FWD
```

A model may be strong overall but weak for one position.

---

# 64. Price segmentation

Evaluate:

```text
budget
mid-price
premium
```

players separately.

This can expose systematic model bias.

---

# 65. Ownership segmentation

Ownership should not be a default predictor of quality, but backtest metrics may be reported by ownership group to identify data-quality differences.

---

# 66. Early-season evaluation

Report separately:

```text
GW1-5
GW6-15
GW16+
```

Early-season forecasting is fundamentally harder due to smaller current-season samples.

---

# 67. Promoted-team evaluation

Create dedicated metrics for:

```text
promoted teams
```

especially early season.

---

# 68. New-signing evaluation

Dedicated subset:

```text
first 1-5 PL fixtures after transfer
```

This tests cross-league and prior logic.

---

# 69. Injury-return evaluation

Evaluate predictions for:

```text
first match back
second match back
third match back
```

especially xMins.

---

# 70. New-manager evaluation

Evaluate:

```text
matches 1-3
matches 4-8
matches 9+
```

after managerial changes.

---

# 71. Calibration plots

Required outputs:

```text
reliability diagram
```

for:

```text
P(start)
P(60+)
P(goal)
P(assist)
P(clean sheet)
P(return)
```

---

# 72. Calibration slope/intercept

Where useful, compute:

```text
calibration intercept
calibration slope
```

to identify systematic under/overconfidence.

---

# 73. Brier score

For binary event probability `p` and outcome `y`:

```text
Brier = mean((p - y)^2)
```

Lower is better.

Use for:

```text
start
goal
assist
clean sheet
return
threshold probabilities
```

---

# 74. Log loss

Use log loss for probability quality.

It strongly penalizes:

```text
high-confidence wrong predictions
```

which is useful for detecting overconfidence.

---

# 75. Ranking versus calibration

Do not select models solely because they rank players well.

Example:

Model A:

```text
good ranking
bad calibration
```

Model B:

```text
slightly worse ranking
excellent calibration
```

Downstream Monte Carlo may benefit more from calibrated probabilities.

Model selection should consider both.

---

# 76. Metric hierarchy

Recommended priority:

```text
1. leakage safety
2. calibration
3. predictive likelihood/error
4. ranking quality
5. downstream optimizer performance
6. computational cost
```

---

# 77. Baseline requirement

Every advanced model must be compared to a simpler baseline.

No baseline:

```text
no evidence complexity helps
```

---

# 78. Statistical significance

Do not overreact to tiny metric differences.

Use:

```text
bootstrap confidence intervals
```

or equivalent temporal resampling where appropriate.

---

# 79. Block bootstrap

Because football observations are temporally correlated, prefer:

```text
Gameweek-level
or
time-block bootstrap
```

over naive row-level bootstrap for some comparisons.

---

# 80. Model promotion rule

An advanced model may replace baseline only if:

```text
out-of-sample improvement is meaningful
calibration does not materially worsen
improvement exists across multiple periods
runtime/complexity remain acceptable
```

---

# 81. Do not promote based on one season

A model should not be selected only because it dominates one unusual season.

Prefer robustness across:

```text
multiple seasons
multiple phases
multiple player groups
```

---

# 82. Ablation testing

For complex models, remove feature groups.

Examples:

```text
without bookmaker odds
without tactical context
without congestion
without previous-season prior
without cross-league adjustment
```

Measure performance change.

---

# 83. Why ablations matter

They answer:

```text
IS THIS DATA ACTUALLY HELPING?
```

and prevent unnecessary complexity.

---

# 84. Data-source ablation

Because the project uses several free sources, compare:

```text
FPL only
FPL + Vaastav
FPL + API-Football
FPL + tactical context
full free stack
```

where feasible.

---

# 85. Optional-provider future evaluation

If a paid provider is ever considered:

it must be evaluated as:

```text
same model
same historical period
free data stack
vs
paid enriched stack
```

Only pay if improvement justifies cost.

---

# 86. End-to-end projection baselines

Required simple projection baselines:

```text
FPL points per game
FPL points per 90
rolling xGI + fixture
simple expected minutes × per90
```

---

# 87. Market baseline

Where pre-deadline bookmaker data exists:

compare internal model against market-implied:

```text
team goals
clean-sheet probabilities
```

The model does not necessarily need to beat bookmakers everywhere to be useful, but market comparison is an important benchmark.

---

# 88. Optimizer backtesting

Optimizer should be tested separately from prediction-model quality.

At each historical deadline:

```text
1. reconstruct valid squad state
2. generate historical projections
3. run optimizer
4. record recommended action
5. advance historical state
```

---

# 89. Optimizer modes

Test:

```text
real historical squad
synthetic squads
```

Both are useful.

---

# 90. Real-manager historical backtest

If historical squad states are available:

simulate management from those exact states.

Track:

```text
bank
purchase prices
selling prices
FT
chips
```

---

# 91. Synthetic squad testing

Generate many valid squad states.

Reason:

One real squad exposes only one decision situation per GW.

Synthetic states increase coverage of:

```text
injuries
FT counts
budget structures
team compositions
```

---

# 92. No-transfer baseline

Mandatory optimizer baseline:

```text
keep squad
roll FT
optimize XI/captain
```

---

# 93. Greedy one-GW baseline

Required:

```text
select transfer maximizing next-GW EV
```

---

# 94. Simple horizon baseline

Required:

```text
select transfer maximizing static 6GW EV difference
```

without future FT planning.

---

# 95. Optimizer comparison

Advanced optimizer should be compared against:

```text
NO TRANSFER
GREEDY 1GW
STATIC 6GW
```

---

# 96. Realized optimizer return

For every recommended transfer calculate future realized:

```text
1GW gain
3GW gain
6GW gain
```

relative to baseline action.

---

# 97. Hit backtesting

Analyze recommendations involving:

```text
-4
-8
...
```

separately.

Measure:

```text
expected net gain
realized net gain
```

---

# 98. Hit confidence buckets

Group hit recommendations by predicted net advantage:

```text
0-1
1-2
2-4
4+
```

Determine whether small-positive hits are actually reliable enough.

---

# 99. Roll FT backtesting

Measure situations where optimizer recommended:

```text
ROLL_FT
```

Compare against best available immediate transfer.

Evaluate later:

```text
did extra FT flexibility create value?
```

---

# 100. Captain backtesting

At every historical GW compare:

```text
optimizer captain
highest EV captain
highest ownership captain optional
actual top scorer hindsight diagnostic only
```

Metrics:

```text
average captain points
captain EV
haul rate
blank rate
```

---

# 101. Vice-captain backtesting

Evaluate:

```text
captain DNP scenarios
```

to ensure vice strategy adds value.

---

# 102. Bench backtesting

Compare:

```text
optimized bench order
EV-sorted bench
price-sorted bench
```

Measure autosub points recovered.

---

# 103. Chip backtesting

Evaluate each chip separately:

```text
Wildcard
Free Hit
Bench Boost
Triple Captain
```

---

# 104. Triple Captain baseline

Compare optimizer TC timing against:

```text
highest projected captain DGW
```

heuristic.

---

# 105. Bench Boost baseline

Compare against:

```text
GW with highest raw bench EV
```

---

# 106. Free Hit baseline

Compare against:

```text
largest blank-GW squad deficit
```

heuristic.

---

# 107. Wildcard baseline

Compare against simple trigger:

```text
current squad 6GW EV
vs
best wildcard squad 6GW EV
```

---

# 108. Chip opportunity cost

When testing chip timing:

include future candidate chip opportunities.

Do not evaluate:

```text
chip used now
```

against:

```text
never use chip
```

only.

---

# 109. Two-half chip seasons

For seasons with multiple chip periods:

backtest the rules applicable to that season.

Chip expiration must be part of historical state.

---

# 110. Decision-quality versus outcome

A correct probabilistic decision can lose in one realization.

Therefore optimizer must be evaluated over:

```text
many decisions
```

not anecdotes.

---

# 111. Expected regret

Optional useful metric:

```text
regret =
best action under model's pre-deadline information
-
chosen action
```

This evaluates optimizer correctness independently from football randomness.

---

# 112. Hindsight regret

Can also calculate:

```text
best realized action
-
chosen realized action
```

but label clearly as:

```text
HINDSIGHT DIAGNOSTIC
```

not fair decision-quality measure.

---

# 113. Sensitivity validation

The Sensitivity Engine outputs:

```text
recommendation_confidence
```

This confidence itself must be validated.

---

# 114. Confidence calibration

Example:

Recommendations labeled:

```text
90% stable
```

should be materially more robust than:

```text
55% stable
```

recommendations.

---

# 115. Decision-margin evaluation

Group optimizer decisions by:

```text
objective margin
```

Check whether:

```text
larger predicted advantage
```

corresponds to more reliable realized advantage.

---

# 116. Model uncertainty validation

Players with high:

```text
projection_uncertainty
```

should exhibit higher forecast error on average.

If not:

uncertainty model is not informative.

---

# 117. Minutes uncertainty validation

Likewise:

```text
high minutes uncertainty
```

should correlate with greater xMins error.

---

# 118. Cross-league uncertainty validation

New foreign-league signings should initially have:

```text
higher uncertainty
```

and that uncertainty should reduce as Premier League evidence accumulates.

---

# 119. Monte Carlo convergence validation

For historical projection run:

compare:

```text
1k
5k
10k
25k
```

simulations.

Metrics:

```text
EV difference
rank changes
P(return) differences
P(10+) differences
```

---

# 120. Simulation noise threshold

Monte Carlo sampling error should be much smaller than:

```text
model forecast error
```

Otherwise simulation count is too low.

---

# 121. Retraining schedule experiment

Compare:

```text
retrain every GW
retrain every 2 GWs
monthly retrain
incremental update
```

Balance:

```text
performance
runtime
complexity
```

---

# 122. Production parity

Backtesting must imitate production.

If production model:

```text
retrains weekly
```

backtest should retrain weekly.

Do not backtest a stronger unrealistic process.

---

# 123. Hyperparameter search leakage

Hyperparameters selected using validation periods must not see final test-period results.

---

# 124. Experiment registry

Every backtest experiment should record:

```text
experiment_id
created_at

train_period
validation_period
test_period

prediction_timestamps

data_sources
dataset_version
feature_version

model_versions
simulation_version
optimizer_version

hyperparameters

metrics
notes
git_commit
```

---

# 125. Recommended experiment ID

Examples:

```text
BT_TEAM_001
BT_MIN_004
BT_TAL_007
BT_EVENT_012
BT_FULL_003
BT_OPT_006
```

---

# 126. Metrics storage

Store machine-readable metrics.

Recommended:

```text
Parquet
```

or:

```text
DuckDB tables
```

Markdown reports are secondary.

---

# 127. Prediction storage

Historical predictions should also be stored.

This allows later analysis without retraining every model.

Recommended:

```text
data/processed/backtests/predictions/
```

---

# 128. Optimizer recommendation storage

Recommended:

```text
data/processed/backtests/decisions/
```

Store:

```text
squad state
recommended action
alternatives
confidence
future plan
```

---

# 129. Immutable experiment outputs

Once an experiment is finished:

do not silently overwrite it.

New configuration:

```text
new experiment_id
```

---

# 130. Comparative reports

Generate reports comparing:

```text
baseline
candidate
```

for every major model change.

---

# 131. Report structure

Recommended:

```text
Experiment
Data period
Model
Baseline

Primary metrics
Calibration
Segments
Runtime
Leakage checks
Conclusion

PROMOTE / REJECT
```

---

# 132. Automatic promotion

Do not automatically deploy a model because one metric improves.

Promotion should require configured validation gates.

---

# 133. Validation gates

Example:

```text
Team Strength:
better NLL
CS calibration not worse

Minutes:
lower MAE
better P(start) Brier

Goal:
better goal log loss

End-to-end:
better player EV calibration
```

---

# 134. Complexity penalty

If two models are statistically similar:

prefer:

```text
simpler
faster
more interpretable
```

model.

---

# 135. Runtime benchmarks

Record:

```text
training time
prediction time
simulation time
optimization time
```

A model improving 0.01% but increasing runtime 100× may not be worthwhile.

---

# 136. Memory benchmarks

Also record peak memory for:

```text
feature generation
training
Monte Carlo
optimization
```

---

# 137. Data availability simulation

Because production free APIs may have missing data:

test model performance under reduced feature sets.

Example:

```text
full data
without API-Football
without StatsBomb
FPL-only fallback
```

---

# 138. Graceful degradation test

The system should still produce valid projections when optional advanced fields are unavailable.

Quality may decrease.

Pipeline must not silently fail or invent data.

---

# 139. Point-in-time integrity tests

Automated tests must verify:

```text
max(feature_effective_at)
<=
prediction_timestamp
```

for every historical prediction row.

---

# 140. Target-time integrity

Verify:

```text
target_fixture_kickoff
>
prediction_timestamp
```

---

# 141. Snapshot integrity

Historical snapshot selection must satisfy:

```text
snapshot_timestamp
<
or =
prediction_timestamp
```

according to configured strictness.

Recommended:

```text
strictly before
```

deadline when possible.

---

# 142. Season aggregate integrity

No current-season feature may use rows after prediction time.

---

# 143. Manager temporal integrity

Manager spell must satisfy:

```text
effective_from <= prediction_timestamp
```

and:

```text
effective_to > prediction_timestamp
or null
```

---

# 144. Player-team temporal integrity

Same for player-team spell.

---

# 145. Manual-context integrity

Manual overrides used historically must have:

```text
knowledge_created_at <= prediction_timestamp
```

not merely:

```text
effective_from <= prediction_timestamp
```

This distinction prevents retrospective manual hindsight.

---

# 146. Information time versus event time

Maintain where possible:

```text
event_time
```

and:

```text
known_at
```

Example:

Player injury occurs Monday.

Publicly known Tuesday.

For Monday prediction:

```text
not usable
```

For Wednesday prediction:

```text
usable
```

---

# 147. Historical odds integrity

Odds data must include timestamp if used.

If timestamp unavailable:

classify as:

```text
high leakage risk
```

and exclude from strict backtesting.

---

# 148. Backtest modes

Support:

```text
STRICT
STANDARD
RESEARCH
```

---

# 149. STRICT mode

Only use fields with strong point-in-time guarantees.

This should be the primary validation mode.

---

# 150. STANDARD mode

May use some historical datasets where timing is highly likely but not perfectly documented.

All such fields must be flagged.

---

# 151. RESEARCH mode

May test additional high-risk features.

Results must never be confused with production-valid performance.

---

# 152. Primary reported result

Always report:

```text
STRICT OUT-OF-SAMPLE
```

performance as the main benchmark.

---

# 153. Survivorship bias

Do not build historical player universe from:

```text
players currently known today
```

only.

Include players present at historical prediction timestamps.

---

# 154. Delisted players

Players later leaving the league must remain in historical datasets where they existed at that time.

---

# 155. Promoted/relegated teams

Historical league membership must reflect each season correctly.

---

# 156. Identity changes

Provider IDs changing between seasons must resolve through canonical IDs.

Do not accidentally merge two different players with similar names.

---

# 157. Duplicate fixture prevention

Every historical fixture must have one canonical fixture identity.

Postponements/reschedules must not create duplicate target outcomes.

---

# 158. DGW validation

Evaluate Double Gameweeks explicitly.

Check:

```text
two fixture projections
minutes risk
aggregate score
captaincy
```

---

# 159. BGW validation

Evaluate Blank Gameweeks explicitly.

Check optimizer behavior around:

```text
benching
transfers
Free Hit
```

---

# 160. Fixture postponement backtests

Test historical cases where fixtures were postponed late.

This is useful for validating point-in-time schedule logic.

---

# 161. Prediction freeze

For each historical deadline:

create a frozen:

```text
prediction input snapshot
```

before generating projections.

This provides auditability.

---

# 162. Backtest cache

Historical predictions can be expensive.

Cache based on:

```text
prediction_timestamp
dataset_version
feature_version
model_version
configuration_hash
```

---

# 163. Cache invalidation

If any relevant model or feature version changes:

invalidate affected cached predictions.

---

# 164. Parallelization

Historical Gameweeks may be processed in parallel only when doing so does not violate training chronology.

For expanding-window retraining:

later model training may depend on earlier periods.

Be careful.

---

# 165. Reproducibility

Every complete backtest must be reproducible with:

```text
experiment config
git commit
data version
random seed
```

---

# 166. Random seed handling

Use deterministic seeds for:

```text
model initialization
Monte Carlo
synthetic squad generation
bootstrap analysis
```

---

# 167. Multiple seeds

For stochastic ML training:

evaluate several seeds if model variance is material.

Do not report only the luckiest run.

---

# 168. Bootstrap uncertainty

Report confidence intervals for important model comparisons.

Example:

```text
Goal Brier improvement:
-0.006
95% CI [-0.010, -0.002]
```

---

# 169. Practical significance

Even statistically significant improvement may be too small to matter.

Report both:

```text
statistical significance
practical magnitude
```

---

# 170. Optimizer practical significance

A projection model improving slightly may still create meaningful value if it improves:

```text
captain ranking
transfer decisions
```

Therefore component metrics and downstream performance both matter.

---

# 171. Model disagreement analysis

Compare major models where possible.

Example:

```text
baseline xMins
advanced xMins
```

Investigate largest disagreements.

This often reveals:

```text
bugs
leakage
useful context
```

---

# 172. Error analysis

For largest misses, classify reason:

```text
unexpected benching
injury
red card
penalty
role change
provider data error
team model miss
football variance
```

---

# 173. Do not manually fix backtest errors

Error analysis may inform future model design.

Do not retrospectively alter historical inputs simply to make a miss disappear.

---

# 174. Prediction drift monitoring

Backtesting framework should also support production monitoring.

After every real Gameweek:

append:

```text
predictions
actuals
errors
```

to evaluation store.

---

# 175. Rolling production metrics

Maintain:

```text
last 5 GWs
last 10 GWs
season-to-date
```

performance.

---

# 176. Drift alerts

Potential alerts:

```text
minutes MAE materially increases
goal calibration deteriorates
CS probabilities overconfident
player EV systematically high
```

---

# 177. Model retraining trigger

Retraining may be:

```text
scheduled
```

and/or:

```text
drift-triggered
```

Initially prefer predictable scheduled retraining.

---

# 178. Champion/challenger setup

Maintain:

```text
CHAMPION
current production model

CHALLENGER
candidate replacement
```

Run both on historical/current data before promotion.

---

# 179. No silent model replacement

Every promoted model must receive:

```text
new version
```

and a recorded decision.

---

# 180. Baseline persistence

Never delete baseline models.

They remain useful for detecting when a sophisticated model silently breaks.

---

# 181. Sanity dashboard

Recommended summary:

```text
Team xG calibration
Minutes MAE
P(start) Brier
Goal Brier
Assist Brier
CS Brier
FPL EV calibration
Rank correlation
Optimizer gain
Runtime
```

---

# 182. End-to-end metric priority

The ultimate system is designed to improve FPL decisions.

However:

```text
optimizer realized points
```

is extremely noisy.

Therefore final judgment should combine:

```text
well-calibrated component models
+
player EV quality
+
historical decision performance
```

---

# 183. Season score simulation

Optional advanced end-to-end evaluation:

Start with a historical valid squad and allow optimizer to manage it through the entire season.

At each GW:

```text
use only historical deadline data
make decision
advance state
```

---

# 184. Full-season backtest

Track:

```text
total points
transfers
hits
captain points
chip points
bench points
team value
```

---

# 185. Full-season comparison

Compare:

```text
advanced optimizer
no-transfer-ish baseline
greedy optimizer
simple multi-GW optimizer
```

using identical initial squad state where possible.

---

# 186. Multiple starting squads

Do not judge full-season optimizer from one starting squad.

Use:

```text
multiple valid initial squads
```

to reduce path dependence.

---

# 187. Path dependence

FPL optimization is path-dependent.

One early transfer changes:

```text
future budget
selling prices
squad
FT
```

Therefore full-season backtests must propagate state correctly.

---

# 188. Historical price evolution

For full-season simulation, future historical player prices become known only as time advances.

At GW X:

optimizer may use only price state available at GW X.

After deadline:

advance to actual historical GW X+1 price state as part of environment simulation.

---

# 189. Counterfactual selling price

For players the simulated manager owns, selling price depends on:

```text
simulated purchase price
historical current price
```

not the selling price from another real manager's squad.

---

# 190. Counterfactual FT state

Track the simulated manager's own:

```text
free transfer history
```

independently.

---

# 191. Counterfactual chip state

Track chip use chosen by simulated optimizer.

Do not copy later historical human chip use.

---

# 192. Actual future environment

The backtest environment may reveal actual future:

```text
prices
fixtures
injuries
results
```

only once simulated time advances past those events.

---

# 193. Season simulation fairness

All compared strategies must receive identical historical environment information at each timestamp.

---

# 194. Prediction-model frozen comparison

When testing optimizer variants:

prefer using the same frozen player projections.

This isolates:

```text
optimizer improvement
```

from:

```text
prediction-model improvement
```

---

# 195. Optimizer frozen comparison

Likewise, when comparing predictive model versions:

use the same optimizer version where possible.

---

# 196. Experiment isolation

Change one major variable at a time whenever possible.

Examples:

```text
Model A vs B
same data
same simulator
same optimizer
```

---

# 197. Acceptance criteria for component model

A predictive component is accepted when:

1. no leakage is detected,
2. it beats required baseline on meaningful metrics,
3. calibration is acceptable,
4. performance is not limited to one season,
5. segment performance has no severe unexplained failure,
6. model is reproducible.

---

# 198. Acceptance criteria for player projections

Player projection pipeline is accepted when:

1. EV is reasonably calibrated,
2. return/haul probabilities are calibrated,
3. player ranking beats simple baselines,
4. predictions remain useful across positions,
5. DGW/BGW behavior is correct,
6. Monte Carlo error is sufficiently small.

---

# 199. Acceptance criteria for optimizer

Optimizer is accepted when:

1. it never produces invalid FPL states,
2. roll FT is correctly represented,
3. hit costs are correct,
4. selling-price logic is correct,
5. advanced strategy beats or matches simpler strategies out-of-sample,
6. chips behave correctly,
7. recommendations are reproducible,
8. confidence meaningfully identifies unstable decisions.

---

# 200. Acceptance criteria for whole system

The FPL Prediction & Decision Engine is ready for production use when:

```text
DATA
is point-in-time safe

MODELS
beat documented baselines

PROBABILITIES
are calibrated

SIMULATION
is coherent and stable

SCORING
matches historical season rules

OPTIMIZER
produces valid decisions

BACKTESTS
show out-of-sample value

RESULTS
are reproducible
```

---

# 201. Required automated tests

At minimum:

```text
test_no_feature_after_prediction_timestamp

test_target_fixture_after_prediction_timestamp

test_snapshot_before_deadline

test_current_season_rollups_stop_at_prediction_time

test_manager_spell_temporal_validity

test_player_team_spell_temporal_validity

test_manual_override_knowledge_time

test_no_target_lineup_feature

test_no_target_match_stats_feature

test_no_future_odds

test_walk_forward_split_order

test_scoring_rules_match_target_season

test_optimizer_rules_match_target_season

test_reproducible_backtest_seed

test_baseline_results_available

test_experiment_metadata_complete
```

---

# 202. Recommended backtest pipeline

```text
SELECT HISTORICAL GW
        ↓
RESOLVE DEADLINE
        ↓
FREEZE POINT-IN-TIME DATA
        ↓
BUILD FEATURES
        ↓
TRAIN / LOAD VALID MODEL
        ↓
GENERATE TEAM PROJECTIONS
        ↓
GENERATE MINUTES
        ↓
GENERATE TALENT / CONTEXT
        ↓
GENERATE EVENT RATES
        ↓
MONTE CARLO
        ↓
APPLY HISTORICAL FPL RULES
        ↓
STORE PLAYER PROJECTIONS
        ↓
OPTIONALLY RUN OPTIMIZER
        ↓
ADVANCE TIME
        ↓
JOIN ACTUAL OUTCOMES
        ↓
CALCULATE METRICS
```

---

# 203. Codex implementation guidance

DO:

* implement point-in-time split utilities first,
* make prediction timestamp mandatory,
* build leakage assertions into feature generation,
* store frozen historical predictions,
* implement simple baselines,
* use walk-forward evaluation,
* separate model and optimizer evaluation,
* version every experiment,
* persist machine-readable metrics,
* generate calibration reports,
* create reproducible experiment configs.

DO NOT:

* use random train/test split as final evidence,
* use current API state to reconstruct historical injuries,
* use closing odds after historical deadline,
* use target-match lineup as feature,
* use final season aggregates,
* tune repeatedly on final holdout,
* judge model quality from a few famous players,
* declare a transfer model bad because one recommended player blanked,
* overwrite old experiment outputs,
* silently accept missing leakage metadata.

---

# 204. Final principle

Every claim that:

```text
THIS MODEL IS BETTER
```

or:

```text
THIS OPTIMIZER MAKES BETTER FPL DECISIONS
```

must be supported by:

```text
POINT-IN-TIME
WALK-FORWARD
OUT-OF-SAMPLE
REPRODUCIBLE
BACKTESTING.
```

The system must prefer:

```text
A SIMPLE MODEL THAT PROVES IT WORKS
```

over:

```text
A COMPLEX MODEL THAT ONLY LOOKS INTELLIGENT.
```

The ultimate validation rule is:

```text
NO HINDSIGHT.
NO LEAKAGE.
NO CHERRY-PICKING.
NO COMPLEXITY WITHOUT MEASURABLE VALUE.
```

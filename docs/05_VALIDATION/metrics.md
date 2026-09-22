# Validation Metrics Specification

## 1. Purpose

This document defines the canonical metrics used to evaluate every component of the FPL Prediction & Decision Engine.

The project must not select models based on a single metric.

Evaluation must consider:

```text
LEAKAGE SAFETY
CALIBRATION
PREDICTIVE ACCURACY
RANKING QUALITY
DECISION QUALITY
ROBUSTNESS
COMPUTATIONAL COST
```

The most sophisticated model is not automatically the best model.

---

# 2. Metric hierarchy

Recommended priority:

```text
1. Point-in-time correctness
2. Calibration
3. Predictive likelihood / error
4. Ranking quality
5. Downstream FPL projection quality
6. Optimizer decision quality
7. Robustness across segments and seasons
8. Runtime / complexity
```

Any model failing level 1 is rejected regardless of other performance.

---

# 3. Primary versus secondary metrics

Every model must define:

```text
PRIMARY METRICS
```

which decide promotion,

and:

```text
SECONDARY METRICS
```

used for diagnostics.

A model must not be promoted because of an improvement in a secondary metric while materially worsening its primary metrics.

---

# 4. General probability metrics

Use for:

```text
P(start)
P(60+)
P(goal)
P(assist)
P(clean sheet)
P(return)
P(10+)
```

Primary metrics:

```text
Brier Score
Log Loss
Calibration Error
```

---

# 5. Brier Score

For binary outcome:

```text
BS = mean((p - y)^2)
```

where:

```text
p = predicted probability
y ∈ {0,1}
```

Lower is better.

Interpretation:

```text
0.00 = perfect
larger = worse
```

Use for all major binary probabilities.

---

# 6. Brier Skill Score

Optional but recommended.

Compare model Brier score against baseline.

```text
BSS =
1 - BS_model / BS_baseline
```

Interpretation:

```text
> 0  model beats baseline
= 0  equal baseline
< 0  worse than baseline
```

Useful for communicating relative improvement.

---

# 7. Log Loss

Binary log loss:

```text
-log(
    y * log(p)
    +
    (1-y) * log(1-p)
)
```

Lower is better.

Log loss strongly penalizes:

```text
high-confidence wrong predictions
```

This makes it particularly useful for detecting overconfident models.

---

# 8. Probability clipping for metrics

Before computing log loss only:

```text
p = clip(p, epsilon, 1-epsilon)
```

Example:

```text
epsilon = 1e-7
```

This is numerical protection only.

Do not use clipping to hide genuinely invalid model probabilities.

---

# 9. Expected Calibration Error

Bucket predicted probabilities.

For each bucket compare:

```text
mean predicted probability
```

with:

```text
observed event rate
```

Then calculate weighted average difference.

Recommended:

```text
ECE
```

as a diagnostic.

---

# 10. Calibration plots

Required for major probabilities.

At minimum:

```text
P(start)
P(60+)
P(goal)
P(assist)
P(clean sheet)
P(return)
```

Plot:

```text
predicted probability
vs
observed frequency
```

with ideal diagonal:

```text
y = x
```

---

# 11. Calibration intercept

Optional.

Ideal:

```text
0
```

Positive/negative intercept can indicate systematic under/overprediction.

---

# 12. Calibration slope

Optional.

Ideal:

```text
1
```

Typical interpretation:

```text
slope < 1
→ predictions too extreme / overconfident

slope > 1
→ predictions insufficiently extreme
```

---

# 13. Continuous prediction metrics

Use for:

```text
expected minutes
expected goals
expected assists
saves
defensive contributions
expected FPL points
```

Primary:

```text
MAE
```

Secondary:

```text
RMSE
Bias
Median Absolute Error
```

---

# 14. Mean Absolute Error

```text
MAE = mean(abs(predicted - actual))
```

Easy to interpret.

Example:

```text
minutes MAE = 13.4
```

means average absolute xMins error of 13.4 minutes.

---

# 15. Root Mean Squared Error

```text
RMSE =
sqrt(mean((predicted - actual)^2))
```

More sensitive to large misses than MAE.

Use diagnostically.

---

# 16. Mean Bias

```text
bias =
mean(predicted - actual)
```

Interpretation:

```text
positive -> systematic overprediction
negative -> systematic underprediction
```

Critical for EV calibration.

---

# 17. Median Absolute Error

Useful when distributions contain extreme outliers.

Example:

```text
unexpected red card
late injury
```

MAE and median AE should often be viewed together.

---

# 18. Count-model metrics

For:

```text
team goals
player goals
saves
defensive contributions
```

use distribution-aware metrics where possible.

Recommended:

```text
Poisson Deviance
Negative Log Likelihood
Negative Binomial Deviance when appropriate
```

---

# 19. Poisson Deviance

Primary for Poisson-style count models.

Useful for:

```text
team goals
xG opportunity counts
player goal counts
save counts
```

when assumptions are reasonable.

---

# 20. Negative Log Likelihood

If model produces a full probability distribution:

```text
NLL =
-negative log probability assigned to actual outcome
```

Preferred over only comparing expected values.

A model predicting the correct mean but wrong variance should be penalized.

---

# 21. Ranked Probability Score

Recommended for ordered score distributions.

Useful for:

```text
team goals
scoreline distributions
minutes buckets
```

RPS rewards probability assigned near the correct ordered category.

---

# 22. Ranking metrics

FPL decisions depend heavily on ordering players.

Primary ranking metric:

```text
Spearman Rank Correlation
```

Optional:

```text
Kendall Tau
NDCG
Precision@K
```

---

# 23. Spearman Rank Correlation

Evaluate relationship between:

```text
predicted player ranking
```

and:

```text
future realized / underlying performance ranking
```

Use by:

```text
position
GW
multi-GW horizon
```

---

# 24. Ranking horizon

Evaluate separately:

```text
1 GW
3 GW
6 GW
```

because different models may be better over different horizons.

---

# 25. Precision@K

Useful for identifying top recommendations.

Example:

```text
Precision@10
```

asks whether players predicted in top 10 tend to belong to top future performers.

Because realized FPL points are noisy, also calculate using:

```text
future xGI
future underlying performance
```

where appropriate.

---

# 26. NDCG

Optional.

Useful when:

```text
correct ranking near the top
```

is more important than exact ordering of low-value players.

Potential use:

```text
transfer candidate ranking
captain candidate ranking
```

---

# 27. Team Strength primary metrics

Primary:

```text
Negative Log Likelihood of score distribution
Poisson Deviance
Brier Score for clean sheet
Clean-sheet calibration error
```

Secondary:

```text
MAE team goals
MAE team xG
Spearman future attack ranking
Spearman future defence ranking
```

---

# 28. Team Strength promotion criteria

Candidate model should generally:

```text
improve score-distribution likelihood
AND
not worsen clean-sheet calibration materially
```

relative to production baseline.

Do not promote solely because:

```text
MAE goals improves slightly
```

while probability calibration worsens.

---

# 29. Minutes Model primary metrics

Primary:

```text
MAE expected minutes
Brier P(start)
Brier P(60+)
Calibration P(start)
Calibration P(60+)
```

Secondary:

```text
Brier P(75+)
Brier P(90)
Log Loss start
Minutes RMSE
Minute-bucket log loss
```

---

# 30. Why P(60+) is primary

The FPL 60-minute threshold directly affects:

```text
appearance points
clean-sheet points
```

Therefore:

```text
P(60+)
```

has disproportionate downstream importance.

---

# 31. Minutes segment metrics

Always report by:

```text
GK
DEF
MID
FWD
```

and preferably:

```text
nailed starters
rotation players
new signings
injury returns
European teams
manager changes
```

---

# 32. Player Talent primary metrics

Talent is latent, so evaluate against future underlying production.

Primary:

```text
MAE future npxG/90
MAE future xA/90
Spearman future npxG/90
Spearman future xA/90
```

Secondary:

```text
shots/90 error
box touches/90 error
team share error
```

---

# 33. Player Talent transfer metrics

Dedicated primary metric:

```text
post-transfer npxG/xA prediction error
```

Compare against:

```text
raw previous-club per90
```

The Talent Model should materially improve transfer translation.

---

# 34. Cross-league metrics

Report by:

```text
source league
```

where sample size permits.

Example:

```text
Championship -> PL
Bundesliga -> PL
La Liga -> PL
Serie A -> PL
Ligue 1 -> PL
```

Do not publish precise league conclusions from tiny samples.

---

# 35. Tactical Context metrics

Direct metrics:

```text
next-match tactical role accuracy
formation accuracy
set-piece hierarchy accuracy
```

More important downstream metrics:

```text
xMins improvement
future xG/xA improvement
EV improvement
```

---

# 36. Goal Model primary metrics

Primary:

```text
Log Loss P(goal)
Brier P(goal)
Goal probability calibration
Poisson Deviance
```

Secondary:

```text
MAE expected goals
Spearman goal threat ranking
```

---

# 37. Assist Model primary metrics

Primary:

```text
Log Loss P(assist)
Brier P(assist)
Assist probability calibration
```

Secondary:

```text
MAE expected assists
Spearman assist threat ranking
```

---

# 38. Clean Sheet Model primary metrics

Primary:

```text
Brier P(team clean sheet)
Brier P(player clean sheet)
Log Loss
Calibration Error
```

Player and team clean-sheet probability must be evaluated separately.

---

# 39. Save Model primary metrics

Primary:

```text
MAE saves
Distribution NLL
Brier P(3+ saves)
```

Secondary:

```text
Brier P(6+)
RMSE saves
```

---

# 40. Defensive Contribution Model metrics

Primary:

```text
Brier threshold reached
MAE defensive contributions
```

Secondary:

```text
Distribution NLL
Calibration threshold probability
```

Evaluate separately by:

```text
DEF
MID
FWD
```

because scoring thresholds differ.

---

# 41. Card Model metrics

Primary yellow:

```text
Brier yellow
Log Loss yellow
```

Primary red:

```text
Brier red
```

Interpret red-card metrics cautiously due to low event frequency.

---

# 42. Bonus Model metrics

Primary:

```text
MAE bonus
Brier any bonus
fixture BPS ranking quality
```

Secondary:

```text
Brier 3 bonus
Spearman BPS rank
```

---

# 43. Monte Carlo metrics

Simulation quality cannot be measured by one number.

Required:

```text
distribution calibration
correlation diagnostics
Monte Carlo convergence
impossible-state rate
```

---

# 44. Monte Carlo convergence

For increasing simulation counts compare:

```text
player EV
P(return)
P(10+)
P(15+)
```

Reference:

```text
large simulation count
```

Measure:

```text
mean absolute difference
maximum difference
ranking changes
```

---

# 45. Monte Carlo standard error

For player EV:

```text
SE(EV) =
std(simulated_points) / sqrt(N)
```

Recommended diagnostic.

---

# 46. Probability Monte Carlo error

For binary event:

```text
SE(p) =
sqrt(p(1-p)/N)
```

Use to determine whether simulation noise is negligible.

---

# 47. Impossible-state rate

Target:

```text
0
```

Examples:

```text
player scores off pitch
negative saves
more player goals than team goals
suspended player plays
```

Any nonzero impossible-state count should be treated as a bug, not model error.

---

# 48. Simulation correlation metrics

Compare historical and simulated correlations such as:

```text
team goals vs player goals
team clean sheet vs defender points
opponent SOT vs GK saves
goals vs bonus
assists vs bonus
```

Potential metric:

```text
absolute correlation difference
```

---

# 49. FPL Projection primary metrics

Primary:

```text
EV Calibration
Mean Bias
Spearman Rank Correlation
Brier P(return)
Brier P(10+)
```

Secondary:

```text
MAE points
RMSE points
P(15+) calibration
```

---

# 50. Why MAE points is not enough

FPL points are highly stochastic.

Example:

Two identical high-quality projections may produce:

```text
2 points
18 points
```

in individual matches.

Therefore:

```text
MAE FPL points
```

must never be the sole model-selection metric.

---

# 51. EV calibration

Group players by predicted EV.

Example buckets:

```text
0-1.9
2.0-2.9
3.0-3.9
4.0-4.9
5.0-5.9
6.0-7.9
8.0+
```

For each bucket report:

```text
count
mean predicted EV
mean actual points
difference
```

---

# 52. EV calibration error

Potential metric:

```text
weighted absolute difference
```

between predicted EV and observed mean across buckets.

Do not overinterpret very small buckets.

---

# 53. Return probability

Define canonically.

Recommended:

```text
attacking_return =
goals > 0
OR
FPL_assists > 0
```

If another definition is used, record it explicitly.

---

# 54. Blank probability

Canonical definition should be configurable.

Recommended user-facing blank:

```text
no goal
no assist
```

Do not confuse with:

```text
low total FPL score
```

---

# 55. Haul metrics

Evaluate calibration of:

```text
P(8+)
P(10+)
P(15+)
```

These are particularly useful for:

```text
captaincy
upside analysis
```

---

# 56. Multi-GW projection metrics

Evaluate cumulative projections over:

```text
3 GW
6 GW
```

Metrics:

```text
MAE cumulative points
Bias
Spearman ranking
top-K performance
```

Only include fixtures that were known in accordance with backtesting rules.

---

# 57. DGW metrics

Report separately:

```text
DGW player EV calibration
DGW xMins error
DGW ranking
```

Because rotation uncertainty is materially different.

---

# 58. Optimizer primary metrics

The optimizer should be evaluated against decision baselines.

Primary:

```text
expected gain over no-transfer baseline
realized gain over no-transfer baseline
gain over greedy 1GW strategy
gain over static 6GW strategy
```

---

# 59. Optimizer realized gain

For decision `A` versus baseline `B`:

```text
realized_gain =
future_points(A)
-
future_points(B)
```

Measure over:

```text
1 GW
3 GW
6 GW
```

---

# 60. Optimizer expected gain

At decision time:

```text
expected_gain =
objective(A)
-
objective(B)
```

This evaluates optimizer logic independently of realized randomness.

---

# 61. Decision hit rate

Potential diagnostic:

```text
percentage of decisions
where recommended action beats baseline
```

Use carefully.

A strategy can have:

```text
< 50% hit rate
```

yet positive EV if wins are larger than losses.

---

# 62. Average decision gain

More important than hit rate:

```text
mean realized gain per decision
```

and:

```text
median gain
```

---

# 63. Cumulative optimizer gain

Over full-season simulations:

```text
total strategy points
-
total baseline points
```

Report across multiple initial squads.

---

# 64. Hit metrics

For paid transfers report:

```text
number of hits
total hit cost
gross points gained
net points gained
average net gain per hit
```

Segment by predicted net-gain bucket.

---

# 65. Roll FT metrics

Measure:

```text
number of roll recommendations
future realized value after roll
FT burn rate at cap
```

Compare against best immediate transfer baseline.

---

# 66. Captain metrics

Primary:

```text
average captain points
expected captain points
captain blank rate
captain 10+ rate
captain 15+ rate
```

Compare to:

```text
highest EV captain baseline
```

---

# 67. Vice-captain metrics

Track:

```text
number of captain DNPs
vice fallback activations
points recovered by vice choice
```

---

# 68. Bench metrics

Track:

```text
autosub points gained
bench-order correctness
bench points wasted
```

Compare with:

```text
simple EV bench order
```

---

# 69. Wildcard metrics

Incremental value:

```text
points with WC path
-
best no-WC path
```

Evaluate over:

```text
3 GW
6 GW
until chip-period end
```

---

# 70. Free Hit metrics

```text
FH incremental points
=
FH squad score
-
best normal-action score
```

Also account for downstream state where relevant.

---

# 71. Bench Boost metrics

```text
BB incremental points
=
15-player scoring result
-
normal XI/autosub result
```

---

# 72. Triple Captain metrics

```text
TC incremental points
=
captain Gameweek score
```

relative to normal 2x captaincy.

---

# 73. Chip opportunity-cost metric

When comparing timing:

```text
chosen chip incremental EV
-
best future available chip opportunity EV
```

Useful for chip timing research.

---

# 74. Sensitivity metrics

Primary:

```text
action_selection_frequency
decision_margin
```

Secondary:

```text
captain_selection_frequency
transfer_selection_frequency
```

---

# 75. Recommendation confidence

Recommended primary raw confidence signal:

```text
action_selection_frequency
```

Example:

```text
best action selected
438 / 500 sensitivity runs
=
87.6%
```

---

# 76. Confidence calibration

Evaluate whether:

```text
high-confidence decisions
```

have:

```text
more stable expected advantages
lower reversal rates
```

than low-confidence decisions.

---

# 77. Decision reversal rate

After reasonable model perturbation:

```text
percentage of runs
where best action changes
```

Equivalent conceptually to instability.

---

# 78. Decision margin

```text
best objective
-
second-best objective
```

Report in expected FPL points.

Large margin:

```text
stronger mathematical preference
```

Small margin:

```text
marginal decision
```

---

# 79. Uncertainty quality metrics

Model uncertainty should itself be predictive.

Example:

Group predictions by:

```text
low
medium
high uncertainty
```

Then compare actual forecast error.

Expected:

```text
higher uncertainty
→ larger average error
```

---

# 80. Uncertainty-error correlation

Possible diagnostic:

```text
Spearman(
    predicted_uncertainty,
    absolute_forecast_error
)
```

Positive values are desirable.

---

# 81. Segment robustness

Every major metric should be segmented where relevant.

Core segments:

```text
season
Gameweek phase
position
home/away
price tier
team strength
```

---

# 82. Special situation segments

Also evaluate:

```text
new signing
new manager
promoted team
injury return
role change
DGW
BGW
European congestion
```

---

# 83. Sample size

Every metric table must include:

```text
N
```

Do not report performance numbers without sample size.

---

# 84. Minimum sample warnings

If:

```text
N < configured_minimum
```

mark result:

```text
LOW SAMPLE
```

Do not make strong conclusions.

---

# 85. Confidence intervals

Recommended for primary metric comparisons.

Possible methods:

```text
block bootstrap
season bootstrap
Gameweek bootstrap
```

depending on metric.

Report:

```text
estimate
95% CI
```

---

# 86. Model delta

For every candidate versus baseline:

```text
delta =
candidate_metric
-
baseline_metric
```

Interpret direction according to metric.

Example:

For Brier:

```text
negative delta = improvement
```

For Spearman:

```text
positive delta = improvement
```

---

# 87. Relative improvement

Optional:

```text
relative_improvement =
(baseline - candidate) / baseline
```

for lower-is-better metrics.

Useful but secondary to absolute changes.

---

# 88. Practical significance

Model promotion should not rely on tiny improvements.

Example:

```text
Brier improves from 0.1810 to 0.1809
```

This may not justify large complexity.

Consider:

```text
effect size
confidence interval
runtime cost
maintenance cost
```

---

# 89. Promotion scorecard

Every model comparison should output:

```text
Leakage: PASS / FAIL

Primary metric 1:
baseline
candidate
delta

Primary metric 2:
baseline
candidate
delta

Calibration:
better / same / worse

Segment robustness:
PASS / WARNING / FAIL

Runtime:
baseline
candidate

Decision:
PROMOTE / REJECT / MORE DATA
```

---

# 90. Automatic rejection conditions

Reject model automatically if:

```text
leakage detected
invalid probabilities
impossible model output
failure on reproducibility tests
```

regardless of predictive metrics.

---

# 91. Calibration rejection

Candidate should normally be rejected if:

```text
predictive error improves marginally
```

but:

```text
probability calibration degrades materially
```

unless a validated calibration layer fixes it.

---

# 92. Segment failure

Do not necessarily reject for one weak small segment.

But reject or investigate if:

```text
major segment
```

shows large systematic degradation.

Example:

```text
Minutes model substantially worse for defenders
```

with large sample size.

---

# 93. Baseline set

Permanent canonical baselines:

## Team

```text
league average
rolling goals
rolling xG
simple Poisson
```

## Minutes

```text
previous match
last-5 minutes
last-5 start rate
```

## Talent

```text
season-to-date per90
EWMA per90
```

## Player points

```text
points per game
points per 90
simple xGI fixture model
```

## Optimizer

```text
no transfer
greedy 1GW
static 6GW
```

---

# 94. Do not remove baselines

Baselines remain permanently available.

They are useful for detecting:

```text
pipeline bugs
model drift
unexpected regressions
```

---

# 95. Metric direction registry

Maintain machine-readable direction.

Example:

```yaml
mae:
  direction: lower

brier:
  direction: lower

log_loss:
  direction: lower

spearman:
  direction: higher

optimizer_gain:
  direction: higher
```

This prevents reporting mistakes.

---

# 96. Canonical metric names

Use stable names such as:

```text
minutes_mae
start_brier
p60_brier

team_goal_nll
team_cs_brier

goal_brier
assist_brier

player_ev_bias
player_ev_spearman

optimizer_gain_vs_roll
optimizer_gain_vs_greedy
```

Do not rename metrics between experiments without versioning.

---

# 97. Metrics table schema

Recommended:

```text
experiment_id

model_name
model_version

metric_name
metric_value

baseline_name
baseline_value

delta
relative_delta

segment_name
segment_value

sample_size

confidence_interval_low
confidence_interval_high

period_start
period_end

created_at
```

---

# 98. Metrics storage

Recommended storage:

```text
DuckDB
+
Parquet
```

Path concept:

```text
data/processed/backtests/metrics/
```

---

# 99. Calibration table schema

Recommended:

```text
experiment_id
metric_target

probability_bucket
prediction_mean
observed_rate

count
absolute_gap
```

---

# 100. Prediction error table

Store individual errors for later analysis:

```text
player_id
fixture_id
prediction_timestamp

prediction
actual
error
absolute_error

segment flags
model version
```

---

# 101. Model comparison report

Every candidate model should produce:

```text
Primary Metrics
Calibration
Segment Results
Baselines
Runtime
Memory
Uncertainty
Leakage Checks
Recommendation
```

---

# 102. Runtime metrics

Track:

```text
feature_generation_seconds
training_seconds
prediction_seconds
simulation_seconds
optimization_seconds
```

---

# 103. Throughput

Optional:

```text
predictions_per_second
fixtures_simulated_per_second
```

Useful when comparing implementations.

---

# 104. Memory metrics

Track:

```text
peak_training_memory_mb
peak_simulation_memory_mb
```

where feasible.

---

# 105. API efficiency metrics

Because the project is free-first:

track:

```text
API requests per update
API cache hit rate
quota utilization
```

particularly for API-Football Free.

---

# 106. Cache hit rate

```text
cache_hits
/
total_requested_resources
```

Higher is generally better for immutable historical data.

---

# 107. Data quality metrics

Track:

```text
missing rate
identity resolution rate
fallback usage rate
manual override rate
```

---

# 108. Identity resolution metrics

Recommended:

```text
auto_match_rate
manual_review_rate
unresolved_rate
high_confidence_match_rate
```

---

# 109. Advanced-field coverage

Track coverage of:

```text
xG
xA
npxG
lineups
formations
injuries
roles
set pieces
```

by:

```text
season
league
player
```

---

# 110. Fallback usage

For each canonical feature:

record:

```text
primary source usage %
fallback usage %
missing %
```

This helps determine whether the free data architecture is sufficient.

---

# 111. Manual override metric

Track:

```text
number of active overrides
percentage of players affected
prediction delta from overrides
```

The system should not require manual corrections for most players.

---

# 112. Leakage metrics

Primary:

```text
number_of_feature_timestamp_violations
```

Required value:

```text
0
```

---

# 113. Snapshot leakage metric

```text
number_of_snapshots_after_prediction_timestamp
```

Required:

```text
0
```

in strict mode.

---

# 114. Future fixture leakage metric

```text
number_of_unknown_at_time_fixtures_used
```

Required:

```text
0
```

---

# 115. Manual hindsight leakage metric

```text
manual_context_created_after_prediction_time_used
```

Required:

```text
0
```

---

# 116. Model reproducibility metric

Given same:

```text
data
config
seed
code version
```

outputs should match.

Track:

```text
max_absolute_reproduction_difference
```

Expected near:

```text
0
```

within numerical tolerance.

---

# 117. Solver correctness metric

For small synthetic optimization problems:

compare MILP solution with brute force.

Metric:

```text
objective_gap_vs_bruteforce
```

Required:

```text
0
```

within tolerance.

---

# 118. Solver optimality gap

For production runs:

record:

```text
solver_optimality_gap
```

Preferred:

```text
0
```

or extremely small.

If nonzero:

expose it.

---

# 119. Simulation impossible-state metrics

Track counts for:

```text
off_pitch_goals
off_pitch_assists
negative_saves
team_goal_mismatch
invalid_lineup
```

All targets:

```text
0
```

---

# 120. Full-season strategy metrics

For historical season simulation:

```text
total_points
average_GW_points
hits_taken
hit_cost
captain_points
bench_points
chip_incremental_points
ending_team_value
```

---

# 121. Relative full-season metrics

Compare strategies:

```text
points_vs_no_transfer
points_vs_greedy
points_vs_static_horizon
```

across multiple initial squads.

---

# 122. Strategy variance

Report:

```text
mean
median
std
p10
p90
```

of season gain across starting squads.

Do not report only the best simulated season.

---

# 123. Win rate versus baseline

```text
percentage of starting squads
where advanced strategy beats baseline
```

Useful alongside average gain.

---

# 124. Worst-case behavior

Report:

```text
p10 strategy gain
worst observed gain
```

to detect unstable optimizer behavior.

---

# 125. Model robustness across seasons

For every primary metric report:

```text
per-season result
overall weighted result
```

Do not hide a weak season inside one aggregate.

---

# 126. Weighted versus macro averages

Use both where useful.

Micro:

```text
weighted by observations
```

Macro:

```text
equal average across seasons
```

Macro helps prevent one large season from dominating.

---

# 127. Current-season monitoring metrics

After every Gameweek track:

```text
minutes_mae
start_brier
goal_brier
assist_brier
cs_brier
EV bias
EV rank correlation
```

---

# 128. Rolling windows

Monitor:

```text
last 5 GW
last 10 GW
season-to-date
```

---

# 129. Drift indicators

Possible:

```text
metric degradation versus historical distribution
calibration shift
feature distribution drift
```

---

# 130. Feature drift

Optional future:

```text
Population Stability Index
KS statistic
Wasserstein distance
```

for important continuous features.

Do not overengineer initially.

---

# 131. Prediction distribution drift

Monitor:

```text
mean xMins
mean P(goal)
mean EV
```

over time.

Sudden unexplained shifts may reveal pipeline bugs.

---

# 132. Alert severity

Potential:

```text
INFO
WARNING
CRITICAL
```

Example:

```text
CRITICAL:
future timestamp leakage detected

WARNING:
minutes MAE increased 20% over 10 GWs
```

---

# 133. Champion versus challenger

Every challenger report should compare identical periods.

Output:

```text
Champion metric
Challenger metric
Delta
Confidence interval
```

---

# 134. Promotion decision

Canonical:

```text
PROMOTE
REJECT
KEEP TESTING
```

---

# 135. Promotion requirements

A candidate should generally satisfy:

```text
no leakage
no correctness regression
primary metrics improve or remain statistically equivalent
calibration acceptable
segment robustness acceptable
runtime practical
```

---

# 136. Equivalent performance

If candidate is statistically equivalent to champion:

prefer:

```text
simpler
faster
more interpretable
```

model.

---

# 137. Research-only metrics

Some metrics are diagnostic and must not decide production alone.

Examples:

```text
ROC-AUC
R²
feature importance
SHAP magnitude
training loss
```

These may be useful but are not primary production metrics.

---

# 138. ROC-AUC

Useful for:

```text
P(start)
```

diagnostics.

But a model with high AUC can still have:

```text
poor probability calibration
```

Therefore never use AUC alone.

---

# 139. R²

May be reported for continuous models.

Do not use as primary for:

```text
minutes
goals
FPL points
```

because error/calibration metrics are more directly useful.

---

# 140. Training metrics

Training loss is useful for optimization diagnostics only.

Never claim:

```text
low training loss
```

means strong model.

---

# 141. Statistical significance threshold

Default conventional reporting:

```text
95% confidence interval
```

but do not turn this into rigid:

```text
p < 0.05 = good
```

decision making.

Practical value also matters.

---

# 142. Metric rounding

Store full precision internally.

Display examples:

```text
Brier: 0.1734
MAE: 12.7
Spearman: 0.421
EV gain: +1.38
```

Do not round before comparison.

---

# 143. Missing metric behavior

If metric cannot be computed due to insufficient sample:

return:

```text
NULL
```

plus:

```text
reason
```

Do not return zero.

---

# 144. Metric validation

Metric implementation itself requires tests.

Examples:

```text
perfect binary prediction -> Brier = 0

perfect continuous prediction -> MAE = 0

identical ranks -> Spearman = 1

reverse ranks -> Spearman = -1
```

---

# 145. Calibration-test fixture

Synthetic:

```text
100 predictions at 0.7
70 positives
30 negatives
```

should produce near-perfect empirical calibration for that bucket.

---

# 146. Optimizer metric tests

Synthetic decisions with known future points should verify:

```text
gain calculation
hit-cost subtraction
baseline comparison
```

---

# 147. Metric configuration

Thresholds should live in config where possible.

Example:

```yaml
promotion:
  minutes:
    require_mae_improvement: true
    require_p60_brier_not_worse: true
```

Do not scatter promotion thresholds through Python code.

---

# 148. Recommended primary metric registry

```text
TEAM_STRENGTH

primary:
- team_score_nll
- team_goal_poisson_deviance
- team_cs_brier
- team_cs_calibration


MINUTES

primary:
- minutes_mae
- start_brier
- p60_brier
- start_calibration
- p60_calibration


PLAYER_TALENT

primary:
- future_npxg90_mae
- future_xa90_mae
- future_npxg90_spearman
- future_xa90_spearman


GOALS

primary:
- goal_log_loss
- goal_brier
- goal_calibration


ASSISTS

primary:
- assist_log_loss
- assist_brier
- assist_calibration


CLEAN_SHEET

primary:
- team_cs_brier
- player_cs_brier
- cs_calibration


SAVES

primary:
- saves_mae
- saves_nll
- saves_3plus_brier


DEFCON

primary:
- defcon_mae
- defcon_threshold_brier


BONUS

primary:
- bonus_mae
- bonus_any_brier
- bps_rank_quality


PLAYER_PROJECTION

primary:
- player_ev_bias
- player_ev_calibration
- player_ev_spearman
- player_return_brier
- player_10plus_brier


OPTIMIZER

primary:
- gain_vs_roll_baseline
- gain_vs_greedy_1gw
- gain_vs_static_6gw
- decision_margin
- recommendation_stability
```

---

# 149. Final system scorecard

Recommended dashboard:

```text
DATA SAFETY
Leakage violations: 0

TEAM
Score NLL
CS Brier

MINUTES
MAE
P(start) Brier
P(60+) Brier

PLAYER EVENTS
Goal Brier
Assist Brier
CS Brier

PROJECTIONS
EV Bias
EV Calibration
Spearman
P(return) Brier
P(10+) Brier

OPTIMIZER
Gain vs roll
Gain vs greedy
Gain vs static 6GW

SYSTEM
Runtime
Simulation stability
Fallback usage
Data coverage
```

---

# 150. Acceptance criteria

This metrics framework is accepted when:

1. every model has documented primary metrics,
2. every model has at least one baseline,
3. probability models are evaluated for calibration,
4. ranking quality is measured separately from point accuracy,
5. expected FPL points are evaluated for bias and calibration,
6. optimizer decisions are compared against explicit baselines,
7. sensitivity/confidence is itself validated,
8. metrics are segmented by important situations,
9. sample sizes are always reported,
10. model comparisons support uncertainty/confidence intervals,
11. leakage violations are treated as automatic failures,
12. runtime and complexity are recorded,
13. metric outputs are stored in machine-readable form,
14. historical and current monitoring use the same metric definitions,
15. metric definitions remain stable and versioned.

---

# 151. Codex implementation guidance

DO:

* create one canonical metric registry,
* centralize metric direction,
* implement reusable metric functions,
* store sample size with every metric,
* produce calibration tables,
* compare every candidate with a baseline,
* support segment-level metrics,
* store machine-readable results,
* test metric functions with synthetic examples,
* report uncertainty around model deltas.

DO NOT:

* select models from one metric,
* optimize only training loss,
* use ROC-AUC as the main probability metric,
* use FPL-point MAE alone,
* hide weak segments inside aggregate results,
* report metrics without sample size,
* convert unavailable metrics to zero,
* promote complexity based on microscopic changes,
* ignore calibration,
* ignore leakage simply because prediction metrics look good.

---

# 152. Final principle

The purpose of metrics is not to create a large dashboard.

The purpose is to answer:

```text
DOES THIS CHANGE ACTUALLY MAKE THE SYSTEM BETTER
OUT OF SAMPLE?
```

Every model should be judged using metrics appropriate to its actual task.

The final hierarchy is:

```text
CORRECTNESS
>
CALIBRATION
>
PREDICTIVE QUALITY
>
DECISION QUALITY
>
COMPLEXITY
```

If a simpler model performs equally well:

```text
KEEP THE SIMPLER MODEL.
```

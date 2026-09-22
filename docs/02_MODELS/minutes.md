# Minutes Model Specification

## 1. Purpose

The Minutes Model estimates the probability distribution of player minutes in a target fixture.

It is one of the most important components of the FPL Prediction & Decision Engine because every downstream player projection depends on whether the player:

- starts,
- appears from the bench,
- reaches 60 minutes,
- is substituted early,
- plays the full match,
- misses the match entirely.

The model must not reduce availability to a single binary variable such as:

```text
starter = true / false
```

Instead, it must estimate a full probabilistic minutes distribution.

---

# 2. Core objective

For each player-fixture pair, estimate:

```text
P(0 minutes)
P(1-29)
P(30-59)
P(60-69)
P(70-79)
P(80-89)
P(90+)
```

and derive:

```text
P(start)
expected_minutes
P(60+)
P(75+)
P(90)
```

The model should also expose uncertainty around these estimates.

---

# 3. Stable output contract

Every prediction must return:

```text
player_id
fixture_id
prediction_timestamp

p_zero_minutes
p_start
expected_minutes
p_60_plus
p_75_plus
p_90

minute_bucket_distribution
minutes_uncertainty

availability_confidence
rotation_risk
early_substitution_risk

model_version
dataset_version
feature_version
```

Example:

```text
p_zero_minutes = 0.04
p_start = 0.91
expected_minutes = 82.7
p_60_plus = 0.88
p_75_plus = 0.73
p_90 = 0.44
```

These numbers are illustrative only.

---

# 4. Why a separate Minutes Model is necessary

A player's attacking ability is not enough.

Example:

```text
Player A:
0.55 xGI/90
expected_minutes = 86

Player B:
0.60 xGI/90
expected_minutes = 49
```

Player B may have higher per-90 talent but lower FPL EV.

Minutes therefore must be predicted independently and then passed downstream.

---

# 5. Problem decomposition

Recommended decomposition:

```text
STEP 1
Will the player appear?

        ↓

STEP 2
If appearing, will the player start?

        ↓

STEP 3
If starting, what is the substitution/minutes distribution?

        ↓

STEP 4
If not starting, what is the bench-appearance distribution?
```

This is preferable to a single direct regression if the decomposed approach performs better.

---

# 6. Candidate modelling strategies

The following should be evaluated.

## Baseline A — Previous match minutes

```text
expected_minutes = previous_fixture_minutes
```

Sanity baseline only.

---

## Baseline B — Rolling average

```text
average minutes last 3
average minutes last 5
```

---

## Baseline C — Empirical start/bench model

Estimate:

```text
P(start)
P(bench appearance)
average minutes if starting
average minutes if bench
```

from recent history.

---

## Baseline D — Hurdle model

Recommended strong baseline:

```text
Model 1:
P(appearance)

Model 2:
P(start | appearance)

Model 3:
minutes | start

Model 4:
minutes | bench appearance
```

---

## Advanced candidate — CatBoost

Use CatBoost for:

```text
P(appearance)
P(start)
minutes conditional on start
bench appearance probability
```

because it handles:

- nonlinear interactions,
- categorical features,
- missing data,
- tactical context,
- manager effects.

---

# 7. Preferred architecture

Recommended final architecture:

```text
AVAILABILITY LAYER
        ↓
APPEARANCE MODEL
        ↓
START MODEL
        ↓
STARTER MINUTES MODEL
        ↓
BENCH MINUTES MODEL
        ↓
FULL MIXTURE DISTRIBUTION
```

This creates an interpretable probabilistic model.

---

# 8. Availability layer

Before predicting minutes, construct availability context.

Inputs:

```text
fpl_status
chance_of_playing_next_round
player_news
injury_status
injury_type
injury_start_date
expected_return_date
suspension_status
suspension_matches_remaining
```

Output:

```text
availability_probability
suspension_block
injury_severity_bucket
availability_confidence
```

Hard rule:

If a player is definitely suspended for the fixture:

```text
P(0 minutes) = 1
```

unless the data is contradictory and flagged for review.

---

# 9. Appearance model

Predict:

```text
P(minutes > 0)
```

Important features:

```text
recent appearances
recent starts
bench presence
injury status
suspension status
manager preference
squad competition
fixture congestion
return from injury
transfer/new signing context
```

Target:

```text
appeared = minutes_played > 0
```

Metrics:

```text
Brier score
log loss
calibration
```

---

# 10. Start model

Predict:

```text
P(start | available)
```

Important features:

```text
starts_last_3
starts_last_5
starts_last_10
consecutive_starts
recent_minutes
bench_status_history
tactical_role
starting_position_history
manager_id
manager_rotation_history
squad_competition_score
fixture_importance
rest_days
European/cup scheduling
injury_return
```

Do not assume:

```text
started last match => starts next match
```

The model must learn context.

---

# 11. Starter minutes model

Conditional on starting, estimate the minutes distribution.

Important signals:

```text
average substitution-off minute
median substitution-off minute
sub_off_minutes_last_3
sub_off_minutes_last_5
full_match_rate
P(60+ | start)
P(75+ | start)
P(90 | start)
position
tactical_role
age
workload
manager substitution tendencies
score-state sensitivity if historically useful
```

The model may use:

```text
ordinal classification
survival analysis
quantile regression
mixture regression
CatBoost regression/classification
```

Compare through backtesting.

---

# 12. Bench minutes model

Conditional on not starting:

Estimate:

```text
P(bench appearance)
minutes if substituted on
```

Useful features:

```text
bench appearances last 5
substitution-on minute history
position
tactical role
team game-state tendencies
manager substitutions
injury return
competition for place
```

Output:

```text
p_bench_appearance
expected_minutes_if_bench
bench_minutes_distribution
```

---

# 13. Minute buckets

Recommended final buckets:

```text
0
1-29
30-59
60-69
70-79
80-89
90+
```

Why:

- FPL has an important threshold at 60 minutes,
- 75+ and 90 are useful for rotation interpretation,
- early bench appearances need separation.

The exact bucket boundaries may be tuned, but 60 must remain explicit.

---

# 14. Expected minutes

Expected minutes must be computed from the predicted distribution.

Do not independently predict xMins and bucket probabilities if they can become contradictory.

Example:

```text
expected_minutes =
sum(bucket_probability * expected_minutes_within_bucket)
```

or direct integration from a continuous distribution.

Consistency is required.

---

# 15. Key feature families

## Recent selection

```text
starts_last_3
starts_last_5
starts_last_10
consecutive_starts
bench_last_3
bench_last_5
appearance_rate
```

## Recent minutes

```text
minutes_last_match
avg_minutes_last_3
avg_minutes_last_5
avg_minutes_last_10
median_minutes_last_5
```

## Substitution behaviour

```text
avg_sub_off_minute
median_sub_off_minute
sub_off_rate_before_60
sub_off_rate_before_75
full_match_rate
avg_sub_on_minute
```

## Workload

```text
minutes_last_7_days
minutes_last_14_days
matches_last_7_days
matches_last_14_days
rest_days_before_fixture
```

## Congestion

```text
european_match_before
european_match_after
domestic_cup_match_before
domestic_cup_match_after
matches_next_7_days_known
```

## Availability

```text
fpl_status
chance_of_playing
injury_status
expected_return_date
suspension_status
```

## Tactical

```text
tactical_role
starting_position_history
formation
manager_id
role_change_flag
```

## Competition for place

```text
squad_competition_score
credible_alternatives_for_role
competitor_availability
```

---

# 16. Squad competition

This must represent competition for the same role, not total squad size.

Example:

A left winger competes mainly with players who can realistically fill that role.

Potential derived variables:

```text
number_of_available_competitors
competitor_quality_score
competitor_recent_start_share
competitor_minutes_share
```

Do not simply count all midfielders or defenders.

---

# 17. Manager rotation profile

Different managers rotate differently.

Create manager-level historical features:

```text
rotation_rate
repeat_start_rate
average_starter_retention
average_substitution_minute
substitutions_before_60_rate
full_match_rate_by_position
rotation_under_fixture_congestion
```

Use hierarchical shrinkage because some managers have limited data.

---

# 18. Manager change

A new manager is a regime change.

Pre-change rotation patterns should receive less weight.

Possible features:

```text
days_since_manager_change
matches_since_manager_change
new_manager_flag
manager_history_available
```

If the manager has historical data from another club:

it may be used as a prior, adjusted for context.

---

# 19. New signings

New signings are difficult because current-club minutes history is absent.

Use:

```text
previous_club_minutes
previous_club_start_rate
transfer_fee/context optional
new_team_role
manual_context
competition_quality
manager comments only if represented safely
```

Use shrinkage and high uncertainty.

Do not assume a new signing is immediately nailed.

---

# 20. Returning from injury

Injury returns require explicit treatment.

Possible phases:

```text
first match back
second match back
third match back
fully reintegrated
```

Features:

```text
days_out
injury_type
training_return_known
bench_return
minutes_since_return
previous_nailedness
```

Expected minutes should often be lower and uncertainty higher immediately after return.

---

# 21. Minor injury / doubtful status

FPL status fields are informative but imperfect.

The model should combine:

```text
chance_of_playing
news
provider injury status
historical manager behavior
recent training/availability if available
```

Do not blindly set:

```text
chance_of_playing = model probability
```

It is an input, not the target probability.

---

# 22. Suspensions

Suspension rules should be deterministic when confirmed.

For a confirmed suspension:

```text
availability_probability = 0
P(0 minutes) = 1
```

unless the suspension does not apply to the relevant competition.

Competition context must therefore be explicit.

---

# 23. Fixture congestion

Congestion can reduce:

```text
P(start)
expected starter minutes
P(90)
```

but the effect varies by:

```text
manager
player
age
position
importance
European involvement
```

Do not apply a fixed global penalty.

Let the model learn interactions.

---

# 24. European matches

Potential features:

```text
days_since_european_match
days_until_european_match
started_in_europe
minutes_in_europe
travel_distance optional
competition_stage
```

The effect may differ between:

```text
Champions League
Europa League
Conference League
```

and by squad depth.

---

# 25. Domestic cups

Domestic cup matches also affect minutes.

Important:

Cup lineups may reveal hierarchy.

Example:

If a fringe player plays 90 minutes in a cup 3 days before PL:

this may reduce his PL start probability.

If a starter is fully rested in the cup:

this may increase his PL start probability.

The model should capture this through recent workload and selection patterns.

---

# 26. Position-specific behaviour

Minutes patterns differ by role.

Examples:

```text
goalkeepers rarely substituted
centre backs often play 90
wingers are frequently substituted
strikers may be removed at 65-80
```

Therefore include:

```text
fpl_position
tactical_role
```

and interactions with manager.

---

# 27. Goalkeepers

GK minutes deserve a simplified path.

For a fit first-choice goalkeeper:

```text
P(start) near 1
P(90 | start) near 1
```

unless:

```text
injury
suspension
rotation competition
cup-only keeper confusion
```

Use a specialized goalkeeper branch if it improves calibration.

---

# 28. Centre backs

CBs tend to have high:

```text
P(90 | start)
```

but may still face:

```text
rotation
injury recovery
fixture congestion
```

Do not hardcode 90.

Use position as a strong prior.

---

# 29. Fullbacks and wingbacks

Often more substitution-sensitive.

Features:

```text
role
formation
manager
recent sub-off pattern
competition
```

are especially important.

---

# 30. Wingers / attacking mids

Typically higher early-sub risk.

The model should distinguish:

```text
nailed starter with 70-minute pattern
```

from:

```text
90-minute talisman
```

This is crucial for FPL EV.

---

# 31. Strikers

Strikers may have:

```text
high start probability
moderate P(90)
```

or be part of a rotation.

Recent substitution pattern is highly informative.

---

# 32. Tactical role changes

A player changing from:

```text
LW -> ST
RB -> RWB
CM -> AM
```

may experience different minute patterns.

Therefore tactical role changes affect not only attacking rates but also xMins.

Use:

```text
role_change_flag
days_since_role_change
matches_in_new_role
```

---

# 33. Formation changes

Formation can alter:

```text
number of available positions for a role
competition for starts
substitution patterns
```

Example:

```text
4-3-3 -> 3-4-2-1
```

may increase/decrease opportunities for certain players.

Do not assume one formation permanently.

Use recent dominant formation and stability.

---

# 34. Starting lineup information

For historical model training:

actual lineup is only a target after the match/lineup event.

For pre-deadline prediction:

future lineup must never be used.

If prediction is generated after official lineup release for a special non-FPL use case:

that must be a separate prediction mode.

Default FPL mode is:

```text
pre-deadline
```

with no future lineup access.

---

# 35. Point-in-time rules

Critical rule:

When predicting GW X:

use only information known before:

```text
prediction_timestamp
```

Forbidden:

```text
future lineup
future injury update
future training report
future suspension
future cup lineup
target-match substitution data
```

---

# 36. Historical injury snapshots

Use:

```text
fplcache
```

and local pre-deadline snapshots where possible.

Never reconstruct historical injury status from today's player profile.

---

# 37. Manual context

Allow manual xMins context overrides.

Example:

```yaml
player_id: ply_x
effective_from: 2026-09-05T10:00:00Z
effective_to: null
context:
  role: first_choice_striker
  confidence: 0.85
reason: "Only natural striker available after transfer window."
```

Manual overrides should modify context, not directly force xMins unless explicitly necessary.

Preferred:

```text
context override -> model feature
```

rather than:

```text
xMins = 90
```

---

# 38. Emergency manual xMins override

Allow only when automated data cannot represent a major known event.

Example:

```text
confirmed suspension rescinded
manager explicitly confirms player will not start
```

If used:

record:

```text
override_value
reason
confidence
author
effective_from
created_at
```

All overrides must be auditable.

---

# 39. Time decay

Recent selection patterns should matter more.

Use exponential decay or equivalent.

Candidate half-lives to test:

```text
3 matches
5 matches
8 matches
30 days
45 days
60 days
```

Selection history may require shorter half-life than player talent.

Do not reuse player-talent decay automatically.

---

# 40. Long-term nailedness prior

Short-term data can be noisy.

Use long-term priors:

```text
season_start_rate
previous_season_start_rate
career_role_start_rate
```

with shrinkage.

This helps after:

```text
one unexpected benching
one injury absence
one cup rotation
```

---

# 41. Early-season behavior

At GW1–GW3:

current-season selection evidence is sparse.

Use:

```text
previous-season role
preseason/new-signing context
manager history
squad depth
manual context
```

with higher uncertainty.

As current-season matches accumulate:

current evidence should dominate.

---

# 42. Small sample handling

Use shrinkage.

Example:

A player with:

```text
2 starts from 2
```

should not automatically have:

```text
P(start) = 1.0
```

Use team/role/manager priors.

---

# 43. Uncertainty

Output must contain uncertainty.

Uncertainty should increase when:

```text
new signing
new manager
new tactical role
returning from injury
small sample
strong squad competition
conflicting data sources
missing lineup history
```

Potential representations:

```text
minutes_std
entropy_of_bucket_distribution
prediction_interval
```

Recommended generic output:

```text
minutes_uncertainty
```

---

# 44. Distribution calibration

Calibration is critical.

Example:

Players predicted with:

```text
P(start) ~ 0.70
```

should start approximately 70% of the time.

Calibration plots:

```text
0.0-0.1
0.1-0.2
...
0.9-1.0
```

Required for:

```text
P(start)
P(60+)
P(90)
```

---

# 45. Evaluation metrics

## Start probability

```text
Brier score
log loss
calibration error
ROC-AUC diagnostic only
```

Do not optimize solely for AUC.

---

## Minutes

```text
MAE minutes
RMSE minutes
median absolute error
```

---

## Buckets

```text
multiclass log loss
ordinal error
calibration by bucket
```

---

## FPL-critical thresholds

Evaluate:

```text
Brier P(60+)
Brier P(75+)
Brier P(90)
```

P(60+) is especially important because of FPL appearance and clean-sheet thresholds.

---

# 46. Segment evaluation

Evaluate separately by:

```text
GK
DEF
MID
FWD
```

and ideally tactical role.

Also:

```text
nailed starters
rotation risks
injury returns
new signings
new-manager periods
European teams
non-European teams
```

---

# 47. Walk-forward validation

Never random-split player fixtures.

Use:

```text
train historical period
predict next GW
advance
retrain/update
```

Example:

```text
Train through GW10 -> predict GW11
Train through GW11 -> predict GW12
```

Across seasons:

```text
Train <= 2023/24 -> test 2024/25
Train <= 2024/25 -> test 2025/26
```

---

# 48. Baseline comparison

Advanced Minutes Model must beat:

```text
previous-match-minutes baseline
rolling-5-minutes baseline
start-rate-last-5 baseline
```

At minimum on:

```text
MAE minutes
Brier P(start)
Brier P(60+)
```

---

# 49. CatBoost implementation option

Potential architecture:

```text
CatBoostClassifier -> P(appearance)
CatBoostClassifier -> P(start | appearance)
CatBoostRegressor/Classifier -> starter minutes
CatBoostRegressor/Classifier -> bench minutes
```

Alternative:

```text
single ordinal CatBoost classifier
```

Compare both.

---

# 50. Hurdle / mixture model

A strong interpretable approach:

```text
P(0)
P(start)
minutes_if_start
minutes_if_bench
```

Then:

```text
full distribution =
P(0)
+
P(start) * starter_distribution
+
P(bench) * bench_distribution
```

This should be the preferred conceptual baseline.

---

# 51. Survival-analysis option

Substitution-off time may be modelled as a survival problem.

For starters:

```text
time_to_substitution
```

with censoring at full time.

Potential methods:

```text
Kaplan-Meier baseline
Cox model
gradient-boosted survival model
```

Only adopt if it improves results.

---

# 52. Ordinal model option

Minutes buckets are naturally ordered.

Possible target:

```text
0
1-29
30-59
60-69
70-79
80-89
90+
```

An ordinal model may improve consistency over independent classifiers.

Evaluate empirically.

---

# 53. Competition for minutes interaction

Model should learn interactions such as:

```text
high squad competition
+
European match in 3 days
+
manager high rotation rate
```

This is where tree-based models may outperform simple rules.

---

# 54. Rotation risk output

Derived output:

```text
rotation_risk
```

Suggested interpretation:

```text
low
medium
high
```

based on:

```text
1 - P(start)
minutes variance
squad competition
manager rotation
congestion
```

Exact thresholds should be configurable.

---

# 55. Early substitution risk

Derived output:

```text
early_substitution_risk
```

Possible metric:

```text
P(minutes < 60 | start)
```

This is especially useful for FPL defenders and midfielders.

---

# 56. Nailedness score

Optional reporting metric:

```text
nailedness_score
```

Could combine:

```text
P(start)
P(75+)
P(90)
```

Example conceptual formula:

```text
0.5 * P(start)
+ 0.3 * P(75+)
+ 0.2 * P(90)
```

Do not use this as a model target.

It is a reporting convenience only.

---

# 57. Bench-risk reporting

For user output:

```text
Player X
P(start): 92%
xMins: 84
P(60+): 89%
P(90): 51%
Rotation risk: Low
```

This is more informative than:

```text
Expected minutes: 84
```

alone.

---

# 58. Interaction with Player Talent Model

Minutes Model answers:

```text
HOW LONG WILL THE PLAYER PLAY?
```

Player Talent Model answers:

```text
HOW PRODUCTIVE IS THE PLAYER PER UNIT OF PLAYING TIME?
```

Do not mix these responsibilities.

---

# 59. Interaction with Goal/Assist Models

Event rates should be integrated over minutes distribution.

Do not always use:

```text
per90_rate * expected_minutes / 90
```

if event probability is nonlinear.

Preferred:

Monte Carlo samples player minutes and then applies event rates.

---

# 60. Interaction with Clean Sheet scoring

For defenders/midfielders:

clean-sheet points require specific FPL minute rules.

Therefore:

```text
P(team clean sheet)
```

must be combined with:

```text
minutes distribution
```

in simulation/scoring.

A defender with:

```text
xMins = 58
```

can have materially lower clean-sheet EV than one with 84.

---

# 61. Interaction with bonus

More minutes usually increase BPS opportunity.

Bonus Model should consume sampled/predicted minutes.

---

# 62. Model update frequency

For current FPL predictions:

refresh xMins when:

```text
new injury news
new suspension
new transfer
European/cup match completed
manager press conference information enters structured/manual context
new lineup information from previous fixture
```

At minimum:

```text
once before each FPL deadline
```

---

# 63. Prediction modes

Support:

```text
pre_deadline
historical_backtest
```

Optional future:

```text
post_lineup
```

Default FPL planning mode:

```text
pre_deadline
```

The post-lineup mode must never contaminate pre-deadline backtesting.

---

# 64. Feature importance

For tree-based models:

store:

```text
global feature importance
SHAP diagnostics
```

Useful for detecting suspicious leakage.

Example red flag:

```text
future lineup field appears as top feature
```

---

# 65. Leakage diagnostics

Automated tests must assert:

```text
all feature timestamps <= prediction_timestamp
```

Additionally inspect suspicious features such as:

```text
current-season final starts
final minutes totals
future injuries
future formations
future squad status
```

---

# 66. Missing data policy

If advanced lineup data is unavailable:

fallback to:

```text
FPL starts/minutes history
manual context
team role priors
```

Do not fail the entire model.

Missing advanced fields must remain explicit.

---

# 67. Free-data architecture

The model must work with:

```text
Official FPL API
Vaastav
fplcache
API-Football Free
StatsBomb Open Data when covered
manual context
```

No paid provider is required.

---

# 68. Request-quota awareness

API-Football Free has limited daily requests.

Minutes Model data ingestion must therefore prioritize:

```text
lineups
formations
injuries
sidelined
```

and cache historical responses.

Never repeatedly refetch immutable lineup data.

---

# 69. Data contract

Minimum historical training row:

```text
player_id
fixture_id
prediction_timestamp

team_id
opponent_team_id

fpl_position
tactical_role

recent_starts
recent_minutes
recent_substitution_pattern

availability_status
suspension_status

rest_days
fixture_congestion

target_started
target_minutes
```

Optional richer features can be joined when available.

---

# 70. Training target timing

Targets:

```text
target_started
target_minutes
target_bench_appearance
```

are derived after the fixture.

Features must be frozen as of historical prediction time.

Training pipeline must explicitly separate:

```text
feature_time
target_time
```

---

# 71. Model artifact

Persist:

```text
model artifact
feature schema
training cutoff
hyperparameters
calibration model
model version
dataset version
feature version
```

---

# 72. Calibration layer

If raw classifier probabilities are poorly calibrated:

evaluate:

```text
isotonic regression
Platt scaling
beta calibration
```

Calibration must be fitted only on validation/training data.

---

# 73. Hyperparameter tuning

Tune with time-aware validation.

Potential parameters:

```text
time decay
rolling windows
CatBoost depth
learning rate
regularization
class weights
minimum samples
injury-return decay
manager-regime decay
```

Never tune directly on the final holdout season.

---

# 74. Experiment sequence

Recommended:

## MIN-001
Previous match minutes baseline.

## MIN-002
Rolling 5 minutes/start baseline.

## MIN-003
Empirical hurdle model.

## MIN-004
Hurdle model + availability.

## MIN-005
Hurdle model + tactical role.

## MIN-006
Hurdle model + congestion.

## MIN-007
CatBoost appearance/start.

## MIN-008
CatBoost starter minutes.

## MIN-009
Bench appearance model.

## MIN-010
Manager rotation features.

## MIN-011
Squad competition features.

## MIN-012
Injury-return regime.

## MIN-013
Full calibrated mixture model.

Do not skip baselines.

---

# 75. Acceptance thresholds

No fixed metric target should be invented before data is available.

However, final model must:

1. beat rolling-minutes baselines,
2. improve P(start) calibration,
3. improve P(60+) Brier score,
4. reduce minutes MAE,
5. perform robustly across multiple seasons,
6. not collapse on early-season data,
7. handle injury returns better than naive baselines,
8. remain stable under missing advanced data.

---

# 76. Sanity tests

Required examples:

```text
confirmed suspension -> P(0) = 1
fit nailed goalkeeper -> high P(start), high P(90)
bench player with no recent starts -> lower P(start)
returning injured player -> higher uncertainty
European congestion -> potentially higher rotation risk
manager change -> uncertainty/regime flag
```

These are behavioral tests, not fixed numeric expectations.

---

# 77. Consistency invariants

Must always satisfy:

```text
0 <= p_zero_minutes <= 1
0 <= p_start <= 1
0 <= p_60_plus <= 1
0 <= p_75_plus <= 1
0 <= p_90 <= 1

p_90 <= p_75_plus <= p_60_plus <= P(appearance)

sum(minute_bucket_distribution) ~= 1

0 <= expected_minutes <= 120
```

If playing only standard Premier League fixtures:

expected minutes should normally be <= 90, but allow broader schema safety.

---

# 78. Interpretation of P(start)

Be explicit:

```text
P(start)
```

means probability the player is in the official starting XI.

It is not:

```text
P(appearance)
```

These must remain separate.

---

# 79. Interpretation of expected minutes

Expected minutes is unconditional.

Example:

```text
90 minutes with 80% probability
0 minutes with 20% probability

xMins = 72
```

Do not report:

```text
90
```

as expected minutes merely because that is expected conditional on start.

---

# 80. Interpretation of p_60_plus

Unconditional probability of the player completing at least 60 FPL-counted minutes.

This is crucial for:

```text
appearance points
clean-sheet eligibility
```

---

# 81. Confidence reporting

Recommended user-facing confidence can derive from:

```text
distribution entropy
data completeness
regime uncertainty
injury uncertainty
model ensemble disagreement
```

Example:

```text
xMins 82
confidence: high
```

versus:

```text
xMins 63
confidence: low
```

---

# 82. Ensemble option

If multiple minutes models perform similarly:

allow ensemble:

```text
statistical hurdle
+
CatBoost
+
role prior
```

Weights should be learned on validation data.

Do not ensemble weak models just for complexity.

---

# 83. Historical manager priors

For new Premier League managers with prior coaching history:

manager substitution and rotation tendencies may be useful.

Use only if:

```text
competition/context mappings are reliable
```

and apply shrinkage toward league average.

---

# 84. Player age

Age may affect:

```text
recovery
rotation
90-minute probability
```

but likely as a weak feature.

Do not impose strong deterministic age penalties.

---

# 85. Match importance

Potential future feature:

```text
relegation battle
title race
derby
knockout context
```

This may affect selection but is difficult to encode robustly.

Do not require it in the first production version unless validated.

---

# 86. Press conference / news NLP

Do not make NLP of manager press conferences a hard dependency.

If added later:

```text
structured news signal
```

should enter availability/manual context.

LLM-generated interpretations must include:

```text
source
timestamp
confidence
```

and must never silently become ground truth.

---

# 87. Optimizer interaction

Decision Optimizer should consume:

```text
expected_minutes
p_start
p_60_plus
minutes_uncertainty
```

not only final EV.

This helps sensitivity analysis understand rotation risk.

---

# 88. Sensitivity analysis

Perturb:

```text
p_start
starter minutes distribution
bench appearance probability
```

according to model uncertainty.

Players with high xMins uncertainty should produce lower recommendation confidence.

---

# 89. User-facing diagnostics

For every player, optionally expose:

```text
P(start)
xMins
P(60+)
P(90)
rotation risk
availability confidence
main xMins drivers
```

Example reasoning:

```text
High P(start):
- started last 6 league matches
- direct competitor injured
- rested in midweek cup match

Reduced P(90):
- manager usually substitutes winger around 72-78'
```

Reasoning should be generated from structured model/context evidence.

---

# 90. Final recommended implementation

Preferred robust architecture:

```text
Availability rules/context
        ↓
Appearance classifier
        ↓
Start classifier
        ↓
Starter minutes distribution
        ↓
Bench appearance/minutes distribution
        ↓
Calibrated mixture
        ↓
xMins + P(start) + P(60+) + P(90)
```

Candidate implementation:

```text
CatBoost + empirical/hurdle baselines
```

with explicit calibration and walk-forward backtesting.

---

# 91. Acceptance criteria

The Minutes Model is accepted when:

1. it returns a coherent minutes distribution,
2. P(start) and P(60+) are calibrated,
3. it beats naive rolling baselines,
4. confirmed suspensions are handled deterministically,
5. injuries and returns are point-in-time safe,
6. manager and tactical regime changes are represented,
7. fixture congestion can affect predictions,
8. bench appearances are modelled explicitly,
9. uncertainty is exposed,
10. missing advanced data does not break the model,
11. historical predictions contain no future lineup information,
12. outputs satisfy all probability invariants,
13. predictions are reproducible and versioned.

---

# 92. Codex implementation guidance

When implementing:

DO:

- build point-in-time training rows,
- implement simple baselines first,
- separate appearance/start/minutes where useful,
- calibrate probabilities,
- support missing advanced data,
- write behavioral and leakage tests,
- persist all model artifacts,
- keep thresholds/config external.

DO NOT:

- predict xMins only from last-match minutes,
- treat FPL chance_of_playing as ground truth probability,
- use future lineups in backtests,
- assume every starter plays 90,
- ignore bench appearances,
- hardcode manager rotation penalties,
- silently force missing values to zero,
- optimize only MAE while ignoring calibration.

---

# 93. Final principle

The Minutes Model should answer:

```text
WHAT IS THE FULL PROBABILITY DISTRIBUTION OF THIS PLAYER'S PLAYING TIME
IN THIS SPECIFIC FIXTURE,
GIVEN EVERYTHING KNOWN BEFORE THE FPL DEADLINE?
```

The objective is not merely low minutes MAE.

The objective is:

```text
CALIBRATED, FPL-USEFUL, OUT-OF-SAMPLE MINUTES PROBABILITIES.
```

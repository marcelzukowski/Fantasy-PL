# Team Strength Model Specification

## 1. Purpose

The Team Strength Model estimates the current attacking and defensive strength of each football team and converts those strengths into fixture-specific expectations.

It is a foundational model for the FPL Prediction & Decision Engine.

The model must estimate, for every target fixture:

- expected goals scored by the home team,
- expected goals scored by the away team,
- expected goals conceded by each team,
- clean-sheet probability,
- probability distribution of team goals,
- current attacking strength,
- current defensive strength,
- uncertainty around all major estimates.

The Team Strength Model must not use FPL points as its primary signal.

It should model football performance first, then feed downstream player and FPL models.

---

# 2. Core modelling principle

The model should separate:

```text
TEAM ATTACKING ABILITY
TEAM DEFENSIVE ABILITY
HOME ADVANTAGE
OPPONENT STRENGTH
RECENCY
TACTICAL / MANAGER REGIME
FIXTURE CONGESTION
```

The central fixture-level problem is:

```text
How many goals is Team A expected to score against Team B,
given everything that was known before the prediction timestamp?
```

Conceptually:

```text
expected_goals_home
    = f(
        home_attack_strength,
        away_defence_strength,
        home_advantage,
        recent_form,
        schedule_strength,
        manager_regime,
        fixture_congestion,
        market_information_optional
      )

expected_goals_away
    = f(
        away_attack_strength,
        home_defence_strength,
        away_context,
        recent_form,
        schedule_strength,
        manager_regime,
        fixture_congestion,
        market_information_optional
      )
```

---

# 3. Primary outputs

The model must expose the following stable contract for every team-fixture pair.

```text
team_id
fixture_id
prediction_timestamp

attack_strength
defence_strength

expected_team_goals
expected_goals_against

clean_sheet_probability

p_score_0
p_score_1
p_score_2
p_score_3
p_score_4
p_score_5_plus

team_score_distribution

strength_uncertainty
expected_goals_uncertainty
clean_sheet_uncertainty

model_version
dataset_version
feature_version
```

For fixture-level use, both teams must be returned coherently.

Example:

```text
Arsenal vs Sunderland

Arsenal expected goals = 2.18
Sunderland expected goals = 0.74

Arsenal clean sheet probability = 0.477
Sunderland clean sheet probability = 0.113
```

These numbers are illustrative only.

---

# 4. Target variables

The model should be trained/evaluated against multiple related targets.

Primary targets:

```text
team_goals_for
team_goals_against
team_xg
team_xga
```

Secondary diagnostic targets:

```text
clean_sheet
score_distribution
shots
shots_on_target
```

Do not rely on a single target.

Goals are the FPL-relevant outcome, but xG contains important information about underlying performance.

---

# 5. Recommended model architecture

The final architecture should be hybrid.

Recommended structure:

```text
LAYER 1
Long-run team strength priors

        ↓

LAYER 2
Recency-weighted xG / goals performance

        ↓

LAYER 3
Opponent-strength adjustment

        ↓

LAYER 4
Dixon-Coles / Poisson fixture model

        ↓

LAYER 5
Optional ML residual correction

        ↓

LAYER 6
Optional bookmaker blend

        ↓

FINAL GOAL DISTRIBUTIONS
```

Do not immediately implement the most complex version.

Each layer must prove value in walk-forward backtesting.

---

# 6. Baseline models

Before implementing the advanced system, create several simple baselines.

## Baseline A — League average

```text
expected_home_goals = historical_league_home_goals_average
expected_away_goals = historical_league_away_goals_average
```

Purpose:

Sanity baseline only.

---

## Baseline B — Rolling goals

Use exponentially weighted:

```text
goals_for
goals_against
```

with home/away adjustment.

Purpose:

Test whether xG actually adds predictive value.

---

## Baseline C — Rolling xG

Use exponentially weighted:

```text
xG_for
xG_against
```

with:

```text
home_advantage
```

Purpose:

Primary simple baseline.

---

## Baseline D — Poisson attack/defence

Standard Poisson model with:

```text
team attack parameter
team defence parameter
league intercept
home advantage
```

Purpose:

Statistical baseline for the final model.

---

# 7. Preferred statistical core

The preferred statistical core is:

```text
Dixon-Coles adjusted Poisson
```

or a closely related hierarchical Poisson model.

Why:

- goals are count data,
- football scores have low counts,
- Poisson is interpretable,
- Dixon-Coles corrects low-score dependence,
- team attack and defence strengths are naturally represented,
- produces full score probability distributions,
- clean-sheet probability follows naturally,
- works well with relatively limited football data.

---

# 8. Dixon-Coles formulation

A classical conceptual formulation:

```text
lambda_home =
    exp(
        league_intercept
        + home_advantage
        + attack_home
        - defence_away
    )

lambda_away =
    exp(
        league_intercept
        + attack_away
        - defence_home
    )
```

Where:

```text
lambda_home = expected goals for home team
lambda_away = expected goals for away team
```

Dixon-Coles correction adjusts probabilities for low-scoring outcomes such as:

```text
0-0
1-0
0-1
1-1
```

The implementation may use an equivalent parameterization if justified.

---

# 9. xG integration

Goals alone are noisy.

The model should incorporate:

```text
team_xg
team_xga
```

as stronger underlying performance indicators.

Possible implementation strategies:

## Option A — Weighted hybrid targets

Estimate team strength using a blend:

```text
performance_signal =
    w_xg * xG
    + w_goals * goals
```

Weights must be selected through backtesting.

Do not hardcode them permanently.

---

## Option B — xG-driven latent strength

Use xG to estimate latent attack/defence strength, then calibrate against actual goals.

This is preferred if it performs better out-of-sample.

---

## Option C — Separate models

Train:

```text
xG model
goal model
```

then blend their fixture predictions.

Again:

final method must be selected by backtesting.

---

# 10. Recency weighting

Recent matches should generally matter more than old matches.

Recommended starting mechanism:

```text
exponential time decay
```

Example concept:

```text
weight = exp(-decay_rate * days_since_match)
```

or:

```text
weight = 0.5 ** (days_since_match / half_life_days)
```

The half-life must be tunable.

Candidate values to test:

```text
30 days
45 days
60 days
90 days
120 days
```

Do not assume one value is correct.

Select by walk-forward validation.

---

# 11. Multiple time scales

A single rolling window may be insufficient.

The model should allow features representing:

```text
very_recent_form
medium_term_form
long_term_strength
```

Example:

```text
last_3_matches
last_5_matches
last_10_matches
season_to_date
previous_season_prior
```

The final model should learn or validate their relative contribution.

---

# 12. Previous-season priors

At the beginning of a season, current-season data is sparse.

The model must not behave as if every team starts from zero information.

Use previous-season information as a prior.

Conceptually:

```text
current_strength =
    prior_strength * prior_weight
    + current_season_evidence * evidence_weight
```

As current-season sample size increases:

```text
prior_weight decreases
```

The decay should depend on:

- number of current-season matches,
- days elapsed,
- regime changes,
- squad turnover if available.

---

# 13. Promoted teams

Promoted teams require special treatment.

Do not directly assume Championship performance transfers one-to-one to Premier League performance.

Possible prior sources:

```text
previous Championship xG strength
promotion status
historical promoted-team performance distribution
league-strength adjustment
bookmaker preseason expectations optional
```

Use hierarchical shrinkage.

A promoted team with excellent Championship numbers should still be shrunk toward a realistic Premier League prior.

---

# 14. Relegated / newly encountered teams in historical cross-league data

If cross-league modelling is introduced:

```text
competition strength must be explicit
```

Do not compare:

```text
2.0 xG/game in Championship
```

directly with:

```text
2.0 xG/game in Premier League
```

without league/context adjustment.

---

# 15. Opponent-strength adjustment

Raw recent xG can be misleading.

Example:

```text
Team A generated 2.0 xG/game
```

but its opponents were weak.

The model should account for:

```text
strength of schedule
```

Preferred approach:

Iterative or hierarchical attack/defence estimation where performance is adjusted by opponent strength.

Avoid simplistic:

```text
last_5_xG_average
```

without opponent adjustment.

---

# 16. Home advantage

Home advantage must be explicitly modelled.

At minimum:

```text
home_attack_effect
home_defence_effect
```

Potentially allow:

```text
team-specific_home_effect
```

only if justified by enough data and regularization.

Default should be league-level home advantage.

Avoid overfitting team-specific home effects.

---

# 17. Attack and defence must be separate

Never represent a team with a single generic strength score.

Required:

```text
attack_strength
defence_strength
```

Examples:

A team may be:

```text
excellent attack
weak defence
```

or:

```text
weak attack
excellent defence
```

This difference is essential for FPL.

---

# 18. Manager regime changes

A manager change can invalidate part of the historical context.

Required features:

```text
manager_id
days_since_manager_change
matches_since_manager_change
manager_change_flag
```

The model should not erase pre-manager data.

Instead, apply regime-aware weighting.

Example conceptual weighting:

```text
post_change_matches -> normal/high weight
pre_change_matches -> reduced weight
```

The reduction strength should be tunable and backtested.

---

# 19. Formation / tactical regime changes

Large tactical changes can also alter team strength.

Examples:

```text
4-3-3 -> 3-4-2-1
deep block -> high press
two-striker system
new defensive structure
```

Possible signal:

```text
formation_change_flag
dominant_formation_recent
formation_stability
```

Do not overreact to one isolated formation change.

Prefer detecting persistent regime changes.

---

# 20. Squad changes

Major transfers can affect team strength before enough matches are played.

Examples:

```text
elite striker joins
starting goalkeeper leaves
multiple starting defenders injured
creative midfielder leaves
```

In the free-data architecture this information may be incomplete.

Therefore:

- allow manual context overrides,
- represent uncertainty,
- avoid pretending the model knows more than it does.

Future versions may add richer squad-value/transfer models.

---

# 21. Injury effects

The Team Strength Model may optionally consume aggregated availability context.

Example:

```text
missing_key_attackers_score
missing_key_defenders_score
```

But do not naively subtract historical FPL points.

Potential approach:

```text
expected_starter_quality delta
```

This is advanced and should only be promoted if it improves backtests.

Primary responsibility for player availability remains with the Minutes Model.

---

# 22. Fixture congestion

Team performance can change under schedule pressure.

Possible features:

```text
rest_days_before_fixture
matches_last_7_days
matches_last_14_days
european_match_before
european_match_after
domestic_cup_match_before
domestic_cup_match_after
```

Use mainly as correction features.

Do not assume congestion always reduces attacking performance by a fixed amount.

Let backtesting determine whether the effect is useful.

---

# 23. Competition context

For Premier League FPL target fixtures:

primary prediction target is Premier League performance.

However, European and cup matches are useful for:

```text
workload
rotation context
recent tactical information
```

Be careful when mixing match-performance statistics from other competitions.

Possible rules:

```text
Premier League performance weight = 1.0
European/cup performance weight = learned or lower prior
```

Never choose arbitrary permanent weights without validation.

---

# 24. Bookmaker information

Market information is optional, not mandatory.

Potential inputs:

```text
home_win_probability
draw_probability
away_win_probability
over_2_5_probability
team_clean_sheet_probability
```

Only information known before `prediction_timestamp` is allowed.

---

# 25. Bookmaker baseline

Create an independent market baseline.

Convert odds into implied probabilities after removing bookmaker margin where feasible.

Use it to answer:

```text
Does our football model beat the market baseline?
```

This is useful even if market data is not used by the final model.

---

# 26. Bookmaker blend

If market information improves predictions:

allow:

```text
final_prediction =
    w_model * internal_model
    + w_market * market_signal
```

Weights must be trained/validated.

Never hardcode:

```text
50/50
```

without evidence.

Market blend should be switchable:

```text
use_market_blend = true/false
```

so backtests can compare both versions.

---

# 27. ML residual correction

Do not replace the statistical core with ML by default.

Preferred approach:

```text
statistical_model_prediction
        ↓
ML predicts residual correction
        ↓
corrected_prediction
```

Candidate model:

```text
CatBoost
```

Possible residual features:

```text
rolling xG
rolling shots
possession
manager regime
congestion
home/away
opponent strength
formation stability
market signals optional
```

Target:

```text
actual_xg - statistical_expected_xg
```

or another carefully defined residual.

Promotion rule:

ML correction is accepted only if it improves out-of-sample calibration and predictive accuracy.

---

# 28. Why CatBoost is preferred for optional correction

Advantages:

- handles nonlinear interactions,
- handles categorical context,
- robust on tabular data,
- supports missing values,
- interpretable through SHAP,
- generally strong without excessive preprocessing.

Still:

CatBoost must beat the simpler statistical baseline.

---

# 29. Hierarchical structure

A hierarchical model is strongly preferred when feasible.

Potential hierarchy:

```text
league
  ↓
season
  ↓
team attack
team defence
```

This allows partial pooling.

Benefits:

- stabilizes new-season estimates,
- reduces overreaction to small samples,
- handles promoted teams better,
- prevents extreme team parameters from tiny datasets.

---

# 30. Expected-goal uncertainty

The output should not be:

```text
Arsenal xG = 2.13
```

with false precision.

Return uncertainty.

Example:

```text
expected_team_goals = 2.13
std = 0.31

or

80% interval = [1.72, 2.55]
```

Exact representation depends on model method.

The downstream simulator should consume this uncertainty when feasible.

---

# 31. Clean-sheet probability

For a Poisson opponent goal rate:

```text
P(clean sheet) = P(opponent goals = 0)
```

For simple Poisson:

```text
P(CS) = exp(-lambda_opponent)
```

If Dixon-Coles or a richer score model is used:

derive clean-sheet probability directly from the full score distribution.

Do not calculate clean-sheet probability from a separate arbitrary heuristic unless proven better.

---

# 32. Score distribution

Return at least:

```text
P(0 goals)
P(1)
P(2)
P(3)
P(4)
P(5+)
```

Internally it is preferable to retain a sufficiently wide distribution, e.g.:

```text
0..8 goals
```

with remaining tail probability aggregated.

This distribution feeds Monte Carlo.

---

# 33. Double-header consistency

For a fixture:

```text
Team A expected goals against
```

must equal:

```text
Team B expected goals for
```

within the same model state.

Do not independently estimate contradictory fixture outputs.

---

# 34. Data input contract

Minimum required historical team-match dataset:

```text
fixture_id
competition_id
season
kickoff_time

team_id
opponent_team_id
is_home

goals_for
goals_against

team_xg
team_xga

prediction_safe_timestamp
```

Recommended additional fields:

```text
shots
shots_on_target
big_chances
possession
field_tilt

manager_id
formation

rest_days
fixture_congestion

market_odds_predeadline
```

---

# 35. Feature families

The feature pipeline may produce:

## Long-term strength

```text
attack_strength_long
defence_strength_long
```

## Recent strength

```text
xg_for_ewm
xga_ewm
goals_for_ewm
goals_against_ewm
```

## Home/away

```text
home_attack_history
away_attack_history
home_defence_history
away_defence_history
```

## Schedule-adjusted

```text
opponent_adjusted_xg
opponent_adjusted_xga
```

## Regime

```text
manager_change_flag
matches_since_manager_change
formation_stability
```

## Congestion

```text
rest_days
matches_last_7
matches_next_7_known
```

## Market optional

```text
market_home_win_probability
market_team_goals_proxy
market_clean_sheet_probability
```

---

# 36. Feature scaling

Statistical count models generally do not require arbitrary standardization.

ML correction may require or benefit from controlled preprocessing.

Preprocessing must be:

- fitted only on training data,
- persisted with model artifacts,
- reproduced during prediction.

Never fit scalers using future test data.

---

# 37. Missing data

Missing advanced team stats must remain:

```text
NULL
```

not:

```text
0
```

Strategies may include:

- model-native missing handling,
- explicit missingness indicators,
- fallback to simpler model,
- shrinkage toward league prior.

The model should degrade gracefully.

Example:

If field tilt is unavailable:

do not fail if the core xG/goal model can still operate.

---

# 38. Early-season behaviour

GW1–GW5 are especially difficult.

Recommended hierarchy of information:

```text
previous-season prior
preseason/market information optional
current-season evidence
```

As matches accumulate:

```text
current-season evidence gains weight
```

The transition must be smooth.

Avoid hard switch:

```text
GW5 = previous season
GW6 = current season only
```

---

# 39. Off-season squad turnover

Previous-season team strength may become stale after major squad turnover.

Potential correction:

```text
squad_turnover_score
```

Not mandatory initially unless reliable data exists.

Manual context may adjust uncertainty or prior strength for extreme cases.

---

# 40. Long-term season drift

Team strength is dynamic.

The model must allow:

```text
attack_strength(t)
defence_strength(t)
```

rather than one static number per season.

Time decay or dynamic latent states should handle this.

---

# 41. Candidate advanced dynamic models

Only consider if simpler versions justify further complexity:

```text
dynamic Bayesian Poisson
state-space attack/defence model
Gaussian random walk latent strengths
Bayesian dynamic generalized linear model
```

Do not start here.

---

# 42. Target leakage rules

When predicting fixture F:

allowed:

```text
all matches completed before prediction_timestamp
known schedule information before prediction_timestamp
known manager information
known injuries/context
predeadline market data
```

forbidden:

```text
target fixture stats
future fixtures' results
future xG
closing odds generated later
future manager appointments
future injury announcements
future table standings
```

League position itself may be used only if computed from matches already completed before prediction time.

---

# 43. Backtesting framework

Use walk-forward validation.

Example:

```text
Train through GW10
Predict GW11

Train through GW11
Predict GW12

Train through GW12
Predict GW13
```

Also test season-level generalization:

```text
Train <= 2023/24
Test 2024/25

Train <= 2024/25
Test 2025/26
```

Do not use random train/test split across matches.

---

# 44. Required evaluation metrics

## Expected goals

```text
MAE team goals
MAE team xG
Poisson deviance
negative log likelihood
```

## Score probabilities

```text
log loss
ranked probability score if implemented
```

## Clean sheet

```text
Brier score
log loss
calibration error
```

## Ranking

```text
Spearman correlation between expected attack output and realized future output
```

---

# 45. Calibration

Calibration is critical.

For all fixtures predicted with:

```text
P(clean sheet) ≈ 0.40
```

approximately 40% should result in clean sheets over a sufficiently large sample.

Produce calibration plots / tables by probability buckets.

Example:

```text
0.0–0.1
0.1–0.2
...
0.9–1.0
```

---

# 46. Evaluation by team strength bucket

Performance should also be evaluated by:

```text
top teams
mid-table teams
weak teams
promoted teams
```

and:

```text
home
away
```

This helps detect systematic bias.

---

# 47. Evaluation around manager changes

Create a dedicated diagnostic:

```text
matches 1–3 after manager change
matches 4–8
matches 9+
```

Compare predictions with and without regime-aware weighting.

The regime component should only remain if it improves predictions.

---

# 48. Evaluation at start of season

Report metrics separately for:

```text
GW1–5
GW6–15
GW16+
```

This verifies whether previous-season priors work.

---

# 49. Baseline promotion rule

A more complex Team Strength Model is promoted only if:

1. it improves out-of-sample predictive likelihood or deviance,
2. clean-sheet probabilities are at least as well calibrated,
3. performance improvement is not isolated to one season,
4. it does not introduce major instability,
5. gains justify maintenance complexity.

---

# 50. Recommended experimentation sequence

Run experiments in this order.

## Experiment TS-001

League-average baseline.

---

## TS-002

Rolling goals + home advantage.

---

## TS-003

Rolling xG + home advantage.

---

## TS-004

Poisson attack/defence model.

---

## TS-005

Dixon-Coles.

---

## TS-006

Dixon-Coles + exponential time decay.

---

## TS-007

Dixon-Coles + time decay + previous-season priors.

---

## TS-008

Opponent-adjusted xG latent strength.

---

## TS-009

Manager regime weighting.

---

## TS-010

Fixture congestion features.

---

## TS-011

CatBoost residual correction.

---

## TS-012

Bookmaker blend.

Do not skip directly to TS-012.

Each experiment should log metrics.

---

# 51. Experiment tracking

Every experiment should record:

```text
experiment_id
training_window
validation_window
features
model_type
hyperparameters
time_decay
prior_settings
market_blend_settings
metrics
git_commit
dataset_version
feature_version
created_at
```

---

# 52. Hyperparameter tuning

Candidate tunable parameters:

```text
time_decay_half_life
previous_season_prior_strength
dixon_coles_rho
hierarchical_prior_strength
manager_regime_decay
ml_residual_hyperparameters
market_blend_weight
```

Use:

```text
walk-forward validation
```

inside tuning.

Never tune directly on final held-out season.

---

# 53. Model artifact

Persist:

```text
team_strength_model artifact
configuration
training_metadata
training_cutoff
feature schema
model version
```

Prediction must be reproducible.

---

# 54. Prediction interface

Recommended conceptual Python interface:

```python
class TeamStrengthModel:
    def fit(self, dataset, as_of):
        ...

    def predict_fixture(
        self,
        fixture_context,
        prediction_timestamp,
    ):
        ...
```

Output:

```python
TeamFixtureProjection(
    fixture_id=...,
    home_team_id=...,
    away_team_id=...,
    home_expected_goals=...,
    away_expected_goals=...,
    home_clean_sheet_probability=...,
    away_clean_sheet_probability=...,
    home_goal_distribution=...,
    away_goal_distribution=...,
    uncertainty=...,
)
```

The exact implementation may differ while preserving the contract.

---

# 55. Interaction with Player Talent Model

The Team Strength Model answers:

```text
How much attacking/defensive opportunity does the TEAM have?
```

The Player Talent Model answers:

```text
How much of that opportunity is this PLAYER likely to capture?
```

Do not duplicate responsibility.

Example:

Team Strength:

```text
Chelsea expected goals = 2.05
```

Player layer:

```text
Palmer expected share / role
João Pedro expected share / role
...
```

Then player fixture event rates are produced downstream.

---

# 56. Interaction with Minutes Model

Team Strength should generally not depend strongly on one player's expected minutes in the first implementation.

However, future advanced corrections may account for expected lineup quality.

If implemented:

```text
expected_lineup_strength
```

must be uncertainty-aware.

Do not create circular dependency:

```text
team strength depends on player xMins
player xMins depends on team strength
```

without an explicit iterative solution.

Initial architecture should avoid this cycle.

---

# 57. Interaction with Monte Carlo

The model supplies:

```text
home goal distribution
away goal distribution
```

or parameters required to generate them.

Monte Carlo should simulate a coherent fixture outcome.

Example:

```text
home goals = 2
away goals = 0
```

Then downstream player event allocation must respect those totals.

---

# 58. Interaction with Clean Sheet Model

The Team Strength Model outputs:

```text
team clean sheet probability
```

The Player Clean Sheet Model modifies this using:

```text
player expected minutes
substitution timing
FPL eligibility rules
```

This separation must remain explicit.

---

# 59. Interpretability output

For every fixture projection, generate diagnostic context.

Example:

```text
Arsenal attack strength: 1.34
Opponent defence strength: 0.82
Home advantage contribution: +0.18 xG
Recent-form adjustment: +0.07 xG
Manager-regime adjustment: +0.03 xG
Market adjustment: disabled

Final expected goals: 2.18
```

Exact decomposition depends on final model.

For ML correction, support SHAP or equivalent diagnostics.

---

# 60. Uncertainty and sensitivity

Team strength uncertainty should be higher when:

```text
newly promoted team
new manager
few current-season matches
major tactical change
missing xG data
large squad turnover
```

Downstream sensitivity analysis should perturb:

```text
expected_team_goals
expected_goals_against
```

according to this uncertainty.

---

# 61. Data freshness

Current predictions must use the latest valid information before the requested prediction timestamp.

Historical predictions must use:

```text
latest valid information available before historical prediction timestamp
```

Never use revised future data silently.

---

# 62. Recommended minimum implementation

The first production-capable implementation should contain:

```text
Dixon-Coles / Poisson core
xG integration
home advantage
opponent adjustment
exponential time decay
previous-season prior
manager-change context
score distribution
clean-sheet probability
uncertainty
walk-forward backtesting
```

These are not a disposable MVP.

They are the minimum robust implementation of the final architecture.

The following may be added only if backtests justify them:

```text
CatBoost residual correction
bookmaker blending
complex formation effects
player-availability team-strength correction
dynamic Bayesian state-space model
```

---

# 63. Acceptance criteria

The Team Strength Model is accepted when:

1. it produces coherent home/away goal distributions,
2. expected goals are non-negative,
3. score-distribution probabilities sum to approximately 1,
4. clean-sheet probabilities are derived consistently,
5. home and away fixture expectations agree across both team records,
6. no future information enters historical predictions,
7. current-season early-GW predictions use shrinkage/priors,
8. promoted teams are handled explicitly,
9. manager changes do not erase historical data,
10. complex versions are compared with baselines,
11. walk-forward backtests are reproducible,
12. calibration is reported,
13. model artifacts are versioned,
14. downstream modules receive the canonical output contract.

---

# 64. Codex implementation guidance

When Codex implements this module:

DO:

- start with tests and data contracts,
- implement baselines first,
- implement the statistical core before optional ML,
- keep model configuration external,
- use point-in-time feature generation,
- write walk-forward evaluation utilities,
- preserve model artifacts and metadata,
- generate calibration diagnostics.

DO NOT:

- train one opaque model on final FPL points,
- use random train/test split,
- use current final league table for historical predictions,
- use future xG or future injuries,
- hardcode arbitrary fixture difficulty multipliers,
- rely on FPL FDR as the main strength model,
- add CatBoost before statistical baselines exist,
- blend bookmakers before measuring the internal model independently.

---

# 65. Final principle

The Team Strength Model should answer:

```text
HOW STRONG IS EACH TEAM RIGHT NOW,
AND WHAT DOES THAT IMPLY FOR THIS SPECIFIC FIXTURE?
```

with calibrated probabilities, explicit uncertainty and no look-ahead leakage.

The primary optimization target is:

```text
OUT-OF-SAMPLE PREDICTIVE QUALITY
```

not complexity.

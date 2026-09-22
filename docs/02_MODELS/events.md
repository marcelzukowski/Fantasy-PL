# Match Event Models Specification

## 1. Purpose

The Event Models convert team strength, player talent, tactical context and expected minutes into probabilities and distributions of football events that generate FPL points.

The Event Models must predict football events first.

They must NOT directly predict total FPL points.

Core events:

```text
goals
assists
clean sheets
goalkeeper saves
penalty saves
defensive contributions
yellow cards
red cards
own goals
missed penalties
bonus / BPS
```

The output of this layer is consumed by:

```text
Monte Carlo Match Simulator
```

which then passes simulated football outcomes to:

```text
FPL Scoring Engine
```

---

# 2. Core architecture

The event layer should follow:

```text
TEAM STRENGTH
        +
PLAYER TALENT
        +
TACTICAL CONTEXT
        +
MINUTES DISTRIBUTION
        +
FIXTURE CONTEXT
        ↓
PLAYER FIXTURE EVENT RATES
        ↓
EVENT MODELS
        ↓
PROBABILITY DISTRIBUTIONS
        ↓
MONTE CARLO
```

---

# 3. Important architectural rule

Do not train:

```text
features -> FPL points
```

as the primary system.

Instead:

```text
features -> football events
football events -> FPL scoring
```

This allows:

* better interpretability,
* correct rule changes,
* correlated Monte Carlo simulation,
* meaningful uncertainty,
* easier debugging,
* reusable football models.

---

# 4. Shared input contract

Every player-fixture event model should have access to:

```text
player_id
team_id
opponent_team_id
fixture_id

prediction_timestamp
kickoff_time

is_home
fpl_position

team_attack_strength
team_defence_strength
opponent_attack_strength
opponent_defence_strength

expected_team_goals
expected_goals_against

player_fixture_event_rates

minutes_distribution
expected_minutes
p_start
p_60_plus

tactical_role
set_piece_context

model_version
dataset_version
feature_version
```

---

# 5. Player Fixture Rate Layer

Before individual event models, create canonical fixture-adjusted rates.

Outputs may include:

```text
fixture_npxg_per90
fixture_penalty_xg_per90
fixture_xa_per90

fixture_shots_per90
fixture_shots_on_target_per90
fixture_box_touches_per90

fixture_defensive_contributions_per90

fixture_saves_per90
fixture_card_rate_per90
```

These rates already incorporate:

```text
Player Talent
Team Strength
Opponent Strength
Tactical Context
```

but NOT realized future minutes.

Minutes are sampled later.

---

# 6. General rate decomposition

Conceptually:

```text
fixture_event_rate
=
player_talent_rate
× team_environment_adjustment
× opponent_adjustment
× tactical_role_adjustment
× set_piece_adjustment
```

The exact mathematical implementation may differ.

Do not hardcode arbitrary permanent multipliers.

All corrections must be:

```text
learned
or
backtested
```

---

# 7. Minutes integration

Do NOT always calculate:

```text
expected_event =
rate_per90 × expected_minutes / 90
```

because:

```text
minutes are uncertain
event probabilities are nonlinear
starts and substitute appearances may have different rates
```

Preferred approach:

```text
sample minutes in Monte Carlo
then sample events conditional on sampled minutes
```

Analytical expected values may still be calculated for diagnostics.

---

# 8. Goal Model

## Purpose

Estimate a player's scoring distribution for a specific fixture.

Outputs:

```text
expected_player_goals
p_goal
p_two_plus_goals
p_three_plus_goals
goal_count_distribution
```

---

# 9. Goal Model inputs

Core:

```text
fixture_npxg_per90
fixture_penalty_xg_per90
minutes_distribution
expected_team_goals
team_goal_distribution
```

Context:

```text
penalty_taker_rank
penalty_taker_confidence
direct_free_kick_rank
tactical_role
```

Optional:

```text
shots_per90
shots_in_box_per90
big_chances_per90
xg_per_shot
bookmaker_anytime_scorer_signal
```

---

# 10. Open-play and penalty goals

Keep separate:

```text
open_play_goal_process
penalty_goal_process
```

Reason:

Penalty role can change abruptly.

A player losing penalties should not require months of rolling xG to adjust.

---

# 11. Non-penalty goal process

Preferred baseline:

```text
Poisson
```

Conditional on:

```text
sampled minutes
fixture npxG rate
```

Conceptually:

```text
lambda_open_play =
fixture_npxg_per90 × minutes / 90
```

Then:

```text
goals_open_play ~ Poisson(lambda_open_play)
```

This is a baseline.

More advanced allocation may be implemented inside match simulation.

---

# 12. Player goals must be coherent with team goals

Critical rule:

Do not independently simulate every player's goals and then obtain:

```text
team goals = 7
```

when the Team Strength Model simulated:

```text
team goals = 2
```

Preferred architecture:

```text
simulate team goals
↓
allocate goals to players
```

or use another coherent joint process.

---

# 13. Goal allocation weights

Potential player goal weights:

```text
fixture_npxg
+
penalty opportunity
+
role
+
minutes
```

Normalize over eligible players.

Example:

```text
player_goal_share =
player_expected_goal_opportunity
/
sum(team_player_goal_opportunity)
```

Then allocate simulated team goals accordingly.

---

# 14. Own goals

Own goals should NOT be included in normal attacking goal allocation.

They are separate rare events.

They may be modelled using:

```text
position prior
minutes
historical own-goal rate
```

A simple population prior is acceptable because the event is very rare.

---

# 15. Penalty occurrence

Penalty scoring requires two probabilities:

```text
P(team receives penalty)
P(player takes penalty | penalty awarded)
```

Then:

```text
P(penalty scored | taken)
```

Potential inputs:

```text
team historical penalty rate
opponent penalty conceded rate
league average
tactical attacking intensity
penalty hierarchy
```

---

# 16. Penalty taker selection

Use:

```text
rank
availability
minutes
confidence
```

If first-choice taker is not on the pitch:

move to next eligible taker.

Monte Carlo should reflect this dynamically.

---

# 17. Penalty conversion

Use strongly shrunk player penalty conversion talent.

Do not infer elite penalty skill from:

```text
3 penalties scored from 3
```

Use:

```text
career sample
league average
shrinkage
```

---

# 18. Missed penalties

A missed penalty must be simulated explicitly because it affects FPL scoring.

Possible outcomes:

```text
scored
saved
off_target_or_post
```

The Scoring Engine later assigns negative FPL points.

---

# 19. Assist Model

## Purpose

Estimate player assist distribution.

Outputs:

```text
expected_player_assists
p_assist
p_two_plus_assists
assist_count_distribution
```

---

# 20. Assist Model inputs

Core:

```text
fixture_xa_per90
minutes_distribution
expected_team_goals
team_goal_distribution
```

Context:

```text
corner_rank_left
corner_rank_right
indirect_free_kick_rank
tactical_role
```

Optional:

```text
key_passes
big_chances_created
crosses
touches_final_third
```

---

# 21. Assist coherence

Assists must be linked to simulated goals.

Do NOT independently simulate:

```text
team goals = 1
player assists total = 4
```

Monte Carlo should assign assist status to compatible team goals.

---

# 22. Unassisted goals

Not every goal has an FPL assist.

Therefore every simulated team goal needs:

```text
assisted
or
unassisted
```

status.

Probability may depend on:

```text
historical league rate
goal type
set piece
penalty
own goal
```

Penalty goals generally have no assist under many scenarios unless FPL rules award one for a foul/handball event.

FPL assist rules must remain in the scoring/event interpretation layer, not assumed identical to official football assists.

---

# 23. FPL assists versus official assists

Very important:

```text
official assist != always FPL assist
```

FPL may award assists in situations not recorded as traditional assists.

The system should distinguish:

```text
football_xA / official assist process
```

from:

```text
FPL assist attribution
```

If detailed event data is insufficient, use historical conversion from official-assist opportunity to FPL-assist probability.

---

# 24. Set-piece assists

Corners and indirect free kicks should adjust assist allocation.

Players with set pieces may have:

```text
higher assist share
```

without necessarily having more open-play creation talent.

Keep the context separate.

---

# 25. Clean Sheet Model

## Purpose

Estimate team and player clean-sheet probability.

Team Clean Sheet comes from Team Strength.

Player Clean Sheet additionally depends on:

```text
minutes
substitution timing
goals conceded after substitution
FPL scoring thresholds
```

---

# 26. Team clean sheet

If opponent goal distribution is known:

```text
P(team clean sheet)
=
P(opponent goals = 0)
```

For Poisson baseline:

```text
P(CS) = exp(-lambda_opponent)
```

For Dixon-Coles:

derive directly from adjusted score distribution.

---

# 27. Player clean sheet

A player can earn clean-sheet points if:

```text
player satisfies FPL minimum-minute condition
AND
team has not conceded while player was eligible/on pitch according to FPL rules
```

Therefore:

```text
player_CS_probability != team_CS_probability
```

in some substitution scenarios.

---

# 28. Example

Defender:

```text
starts
substituted at 65
score at substitution = 1-0
final score = 1-1
```

The player may retain clean-sheet points depending on official scoring rules.

The simulation must track goal timing relative to player substitution.

---

# 29. Goal timing

Monte Carlo should eventually support approximate goal timing.

At minimum:

```text
simulated_goal_minute
```

This enables:

```text
clean-sheet eligibility
substitution interactions
```

A simple uniform or empirically learned timing model may be used initially.

---

# 30. Goal timing model

Possible inputs:

```text
league goal timing distribution
team-specific first/second-half patterns
game state
```

Start simple.

Advanced time-dependent hazard models should only be added if useful.

---

# 31. Goalkeeper Save Model

## Purpose

Predict goalkeeper save distribution.

Outputs:

```text
expected_saves
p_3_plus_saves
p_6_plus_saves
p_9_plus_saves
save_count_distribution
```

---

# 32. Save Model inputs

Core:

```text
expected_goals_against
opponent_attack_strength
opponent_expected_goals
goalkeeper_minutes
```

Recommended:

```text
opponent_shots_on_target_rate
team_shots_on_target_conceded
goalkeeper_save_rate
```

Optional:

```text
post_shot_xg
goalkeeper_shot_stopping_talent
opponent_shot_quality
```

---

# 33. Saves and goals conceded are linked

Do NOT model:

```text
saves
```

completely independently from:

```text
shots on target
goals conceded
```

Conceptually:

```text
shots_on_target_faced
=
saves + goals_conceded
```

excluding unusual events.

Simulation should preserve approximate coherence.

---

# 34. Shots-on-target process

Potential architecture:

```text
opponent attacking strength
↓
expected shots
↓
expected shots on target
↓
goalkeeper saves / goals
```

This may be preferable to a direct save regression.

---

# 35. Goalkeeper talent

Player Talent can supply:

```text
goalkeeper_save_talent
```

Potentially based on:

```text
save rate
PSxG prevented
historical shot-stopping
```

Use strong shrinkage.

---

# 36. Penalty Save Model

Outputs:

```text
p_penalty_faced
p_penalty_saved_given_faced
expected_penalty_saves
```

Use:

```text
team penalty concession rate
opponent penalty-winning rate
league prior
goalkeeper penalty-save history
```

Penalty saves are rare.

Use heavy shrinkage.

---

# 37. Defensive Contribution Model

## Purpose

Predict FPL-relevant defensive contribution events.

This must follow the scoring rules of the relevant FPL season.

Potential underlying actions:

```text
tackles
interceptions
clearances
blocks
recoveries
aerial actions
```

depending on official scoring definition.

---

# 38. Defensive contribution rate

Player Talent supplies a baseline:

```text
talent_defensive_contribution_rate
```

Fixture adjustment uses:

```text
opponent possession
opponent attack volume
player role
expected minutes
team defensive style
```

---

# 39. Defensive contribution outputs

Return:

```text
expected_defensive_contributions
defensive_contribution_distribution
p_reach_defcon_threshold
expected_defcon_points_before_scoring
```

If scoring thresholds differ by FPL position, the scoring rule belongs in:

```text
scoring_rules.yaml
```

not hardcoded here.

---

# 40. Defensive contribution opponent effects

A defender facing a stronger opponent may:

```text
lose clean-sheet probability
```

but gain:

```text
more defensive-action opportunities
```

This tradeoff must be represented.

---

# 41. Defensive contribution position priors

Different roles naturally produce different action rates.

Examples:

```text
CB -> high clearances
DM -> tackles/interceptions
winger -> lower defensive contribution
```

Use tactical role rather than only FPL position.

---

# 42. Card Model

## Purpose

Estimate:

```text
yellow card risk
red card risk
```

Outputs:

```text
p_yellow
p_red
expected_cards
```

---

# 43. Card inputs

Core:

```text
historical_yellow_rate_per90
historical_red_rate_per90
minutes_distribution
tactical_role
```

Optional:

```text
opponent dribble rate
referee card rate
derby flag
match intensity
team pressing
```

---

# 44. Card modelling

Yellow cards may use:

```text
Bernoulli
Poisson
```

conditional on minutes.

Red cards are very rare.

Use:

```text
strong population/role prior
```

and heavy shrinkage.

---

# 45. Second yellow

If detailed modelling is implemented:

distinguish:

```text
straight red
second-yellow red
```

because events are not independent.

Not mandatory initially.

---

# 46. Referee context

Referee may add predictive value.

Potential features:

```text
cards_per_match
fouls_per_card
penalties_per_match
```

But referee assignment must be known before prediction timestamp.

If unavailable historically:

do not use it.

---

# 47. Bonus Model

Bonus is one of the most difficult event components.

Preferred approach:

```text
simulate BPS-relevant match actions
↓
calculate player BPS
↓
rank within fixture
↓
award bonus
```

rather than:

```text
predict final bonus directly
```

---

# 48. Bonus outputs

Return:

```text
expected_bonus
p_bonus_1
p_bonus_2
p_bonus_3
bonus_distribution
```

---

# 49. BPS modelling

Potential inputs:

```text
goals
assists
clean sheets
saves
cards
minutes
goals conceded
winning goal
pass completion
tackles
recoveries
big chances missed
errors
```

depending on current official BPS rules and available data.

---

# 50. Season-specific BPS rules

Never hardcode one permanent BPS system.

Use:

```text
scoring_rules.yaml
```

or dedicated season config.

FPL can change rules.

---

# 51. Simplified Bonus baseline

Initial baseline:

Train model predicting:

```text
expected BPS
```

from:

```text
simulated goals
simulated assists
clean sheets
saves
cards
position
minutes
historical BPS baseline
```

Then assign bonus by ranking simulated players.

This is acceptable before full BPS reconstruction exists.

---

# 52. Bonus must be fixture-relative

A player's bonus probability depends on:

```text
what other players do in the same match
```

Therefore do NOT predict:

```text
P(3 bonus)
```

independently for each player without fixture context.

Monte Carlo should rank players within each simulated fixture.

---

# 53. Bonus tie handling

FPL bonus ties have specific allocation rules.

The Scoring Engine / Bonus Engine must implement current official tie rules through configuration.

---

# 54. Own Goal Model

Rare event.

Potential baseline:

```text
position-specific historical own goal rate
× expected minutes
```

Heavy shrinkage.

No complex model initially.

---

# 55. Missed Penalty Model

Derived from:

```text
penalty awarded
player takes penalty
penalty conversion probability
```

No separate independent regression required initially.

---

# 56. Goals Conceded Scoring Events

For GK/DEF scoring:

need simulated:

```text
goals conceded while player is on pitch
```

not only final team goals conceded.

This requires:

```text
goal timing
player substitution timing
```

in Monte Carlo.

---

# 57. Appearance event

Appearance points are not an Event Model target.

They are derived from:

```text
sampled minutes
```

inside FPL Scoring.

---

# 58. Player-event correlations

Events within a player are correlated.

Example:

Higher minutes increase:

```text
goal probability
assist probability
card probability
defcon probability
bonus opportunity
```

Simulation must use the same sampled minutes for all these processes.

---

# 59. Team-event correlations

Examples:

```text
team scores more
→ more player goal/assist opportunities

team concedes zero
→ all eligible defenders/GK share clean-sheet event
```

Do not independently simulate these.

---

# 60. Opposing-team correlations

Examples:

```text
home goals
```

and:

```text
away clean sheet
```

are mutually exclusive if home goals > 0.

Likewise:

```text
opponent shots
goalkeeper saves
goals conceded
```

must be coherent.

---

# 61. Event simulation hierarchy

Recommended hierarchy:

```text
1. Sample player minutes / starters
2. Sample team score
3. Sample goal timing
4. Allocate goalscorers
5. Allocate assists
6. Simulate goalkeeper shots/saves coherently
7. Determine clean-sheet eligibility
8. Simulate defensive contributions
9. Simulate cards
10. Simulate penalty events
11. Calculate BPS / bonus
12. Pass events to FPL Scoring
```

Exact implementation can evolve.

---

# 62. Team lineup coherence

Monte Carlo should ideally avoid impossible situations such as:

```text
14 players simultaneously playing 90 minutes
```

Initial version may simulate player minutes independently if necessary, but a lineup-coherence layer is strongly preferred.

Long-term target:

```text
11 players on pitch per team
```

subject to substitutions.

---

# 63. Goal allocation and minutes

A player cannot score when:

```text
not on pitch
```

Goal timing must therefore respect:

```text
player entry minute
player exit minute
```

---

# 64. Assist allocation and minutes

Same rule.

Assister must be on pitch when goal occurs.

---

# 65. Penalty taker and minutes

Set-piece hierarchy should be resolved among:

```text
players currently on the pitch
```

not the nominal squad hierarchy alone.

---

# 66. Substitute event rates

A substitute may have a different per-minute attacking rate due to:

```text
game state
fresh legs
short sample
```

Initial model may use same fixture rate.

Future model may include:

```text
starter_vs_substitute adjustment
```

only if validated.

---

# 67. Score-state effects

Advanced future option.

Example:

Team leading 2-0:

```text
slower tempo
less attacking
```

Team trailing:

```text
more attacking volume
```

Event rates may depend on simulated score state.

Do not make this mandatory initially.

---

# 68. Goal timing distribution

Initial baseline:

Use empirical Premier League goal timing distribution.

Potential buckets:

```text
1-15
16-30
31-45+
46-60
61-75
76-90+
```

Later use continuous hazard.

---

# 69. Event-rate uncertainty

Every major event model should expose uncertainty where feasible.

Examples:

```text
goal_rate_uncertainty
assist_rate_uncertainty
save_rate_uncertainty
defcon_rate_uncertainty
```

Monte Carlo can sample model parameters, not just outcomes.

---

# 70. Two kinds of uncertainty

Separate:

```text
aleatoric uncertainty
```

football randomness

from:

```text
epistemic uncertainty
```

uncertainty about true player/team rates.

This distinction matters for sensitivity analysis.

---

# 71. New player uncertainty

A player with:

```text
200 historical minutes
```

should have wider event-rate uncertainty than one with:

```text
5000 minutes
```

even if both have identical point estimates.

---

# 72. Cross-league uncertainty

Players arriving from leagues with weaker data/translation estimates should receive:

```text
wider event-rate uncertainty
```

---

# 73. Model baselines

Each event must have a simple baseline.

Goals:

```text
rolling xG/90 × minutes × fixture strength
```

Assists:

```text
rolling xA/90 × minutes × fixture strength
```

Clean sheet:

```text
Poisson team CS probability
```

Saves:

```text
rolling saves/90
```

Cards:

```text
historical card rate
```

Defcon:

```text
rolling defensive contributions/90
```

Bonus:

```text
historical BPS/90
```

---

# 74. Event-model validation

Evaluate each event separately.

Do not judge the entire event layer only through final FPL point error.

---

# 75. Goal metrics

Required:

```text
Poisson deviance
log loss P(goal)
Brier P(goal)
calibration
MAE expected goals
```

Also:

```text
rank correlation
```

for player goal threat.

---

# 76. Assist metrics

Required:

```text
Brier P(assist)
log loss
calibration
MAE expected assists
```

---

# 77. Clean sheet metrics

Required:

```text
Brier score
log loss
calibration
```

Evaluate separately:

```text
team CS
player CS
```

---

# 78. Save metrics

Use:

```text
MAE saves
Poisson deviance
distribution log likelihood
Brier P(3+ saves)
```

---

# 79. Defensive contribution metrics

Use:

```text
MAE defensive contributions
threshold Brier score
calibration
```

---

# 80. Card metrics

Use:

```text
Brier yellow
Brier red
log loss
calibration
```

Red-card sample is small; interpret carefully.

---

# 81. Bonus metrics

Use:

```text
MAE bonus
Brier any bonus
Brier 3 bonus
rank accuracy within fixture
```

Also compare simulated bonus distribution with actual distribution.

---

# 82. Walk-forward validation

Mandatory.

Example:

```text
train through GW10
predict GW11

train through GW11
predict GW12
```

No random match splitting.

---

# 83. Point-in-time rule

All inputs must satisfy:

```text
feature_effective_at <= prediction_timestamp
```

Forbidden:

```text
target match lineup
target match shots
target match xG
future penalty hierarchy
future injury update
future referee if not yet announced
closing odds after prediction timestamp
```

---

# 84. Outcome data

Target-match event data is allowed only as:

```text
training target
```

never feature.

---

# 85. Calibration requirements

Probability calibration is critical.

For example:

Players receiving:

```text
P(goal) ≈ 0.30
```

should score roughly 30% of the time over a large sample.

Calibration buckets:

```text
0.00-0.05
0.05-0.10
0.10-0.20
0.20-0.30
0.30-0.40
0.40+
```

Use enough observations per bucket.

---

# 86. Position-segment evaluation

Evaluate:

```text
GK
DEF
MID
FWD
```

separately.

Also by tactical role where useful.

---

# 87. Team-strength segment evaluation

Evaluate events for:

```text
elite attacking teams
average teams
weak teams
```

to detect systematic allocation bias.

---

# 88. Home-away evaluation

Check:

```text
home
away
```

separately.

---

# 89. Transfer-player evaluation

Dedicated evaluation for:

```text
new club
new league
new role
```

This checks whether Player Talent + Context translation works.

---

# 90. Double Gameweeks

Event models operate per fixture.

For a Double Gameweek:

```text
Player GW projection
=
Fixture 1 distribution
+
Fixture 2 distribution
```

through simulation/aggregation.

Do not create one artificial combined fixture.

---

# 91. Blank Gameweeks

No fixture:

```text
no event simulation
```

unless rescheduled fixture context exists.

---

# 92. Postponements

Fixture ID remains stable where possible.

If fixture kickoff changes:

use updated schedule only if known before prediction timestamp.

Historical backtest must respect what was known at the time.

---

# 93. Free-data operation

The event layer must work with the free-first data architecture.

Minimum viable inputs:

```text
Official FPL API:
xG
xA
minutes
goals
assists
saves
BPS
defcon where available

Team Strength outputs

API-Football:
lineups
formations
injuries
basic player stats

StatsBomb Open Data:
supplementary event research
```

No paid provider required.

---

# 94. Graceful degradation

If:

```text
box touches
big chances
```

are unavailable:

Goal Model should fall back to:

```text
fixture xG rate
```

If:

```text
PSxG
```

is unavailable:

Save Model falls back to:

```text
shots on target + save rate
```

Never fail the entire pipeline because an optional statistic is missing.

---

# 95. Model selection philosophy

For each event:

```text
simple statistical baseline
↓
calibrated improved model
↓
optional ML correction
```

Promote complexity only if:

```text
walk-forward metrics improve
calibration does not worsen
maintenance cost is justified
```

---

# 96. Candidate ML usage

Possible CatBoost use:

```text
goal-rate residual correction
assist-rate residual correction
save-rate correction
defcon correction
```

ML should consume canonical features.

Do not pass raw provider JSON.

---

# 97. Goal ML correction

Potential target:

```text
future npxG opportunity
```

rather than:

```text
did player score yes/no
```

because realized goals are noisier.

Final goal probability still derives through event distribution.

---

# 98. Assist ML correction

Similarly prefer modelling:

```text
future xA opportunity
```

rather than only realized assists.

---

# 99. Defensive ML correction

Defensive action volume may benefit from nonlinear interactions:

```text
opponent strength
possession
role
formation
minutes
```

CatBoost may be useful here.

---

# 100. Bonus ML model

Bonus may be one area where ML adds more value due to complex BPS interactions.

Still preserve:

```text
fixture-relative ranking
```

rather than independent player prediction.

---

# 101. Event model experiment sequence

Recommended:

## EVT-001

Goal Poisson baseline.

## EVT-002

Team-goal coherent player allocation.

## EVT-003

Penalty process.

## EVT-004

Assist allocation.

## EVT-005

Goal/assist calibration.

## EVT-006

Player clean-sheet eligibility.

## EVT-007

GK save model.

## EVT-008

Penalty-save model.

## EVT-009

Defensive contribution model.

## EVT-010

Card model.

## EVT-011

Simplified BPS/bonus model.

## EVT-012

Goal timing.

## EVT-013

Correlated full fixture event simulation.

## EVT-014

Optional ML residual corrections.

---

# 102. Goal distribution sanity checks

For every player:

```text
P(0 goals)
+
P(1 goal)
+
P(2 goals)
+ ...
≈ 1
```

And:

```text
expected_player_goals >= 0
```

---

# 103. Team-player goal consistency

For each fixture:

```text
sum(player expected goals)
```

should be reasonably coherent with:

```text
expected team goals
```

after accounting for:

```text
own goals
unallocated/other player probability
```

---

# 104. Assist consistency

Expected assists should not systematically exceed plausible assisted-goal volume.

Monitor:

```text
expected team assists
/
expected team goals
```

against league reality.

---

# 105. Save consistency

Monitor:

```text
expected_saves
+
expected_goals_conceded
≈
expected_shots_on_target_faced
```

where data structure supports it.

---

# 106. Clean-sheet consistency

For fixture:

```text
P(home CS)
```

must be consistent with:

```text
away goal distribution
```

and vice versa.

---

# 107. Bonus consistency

Within each simulation:

bonus awards must satisfy official fixture constraints.

Do not give:

```text
3 bonus to five players
```

unless official tie rules actually permit that outcome.

---

# 108. Reproducibility

Every simulation-ready event projection must carry:

```text
prediction_timestamp
model_version
dataset_version
feature_version
```

Random simulation additionally requires:

```text
random_seed
```

---

# 109. Model artifacts

Persist separately:

```text
goal_model
assist_model
save_model
defcon_model
card_model
bonus_model
```

with:

```text
feature schema
training cutoff
hyperparameters
calibration artifacts
```

---

# 110. Event Model API concept

Example:

```python
goal_projection = goal_model.predict(
    player_fixture_context,
    prediction_timestamp,
)
```

Output:

```python
GoalProjection(
    player_id=...,
    fixture_id=...,
    expected_goals=...,
    p_goal=...,
    goal_distribution=...,
    uncertainty=...,
)
```

Equivalent stable contracts should exist for all event models.

---

# 111. Monte Carlo contract

Event models should provide:

```text
distribution parameters
probabilities
uncertainty parameters
```

not already sampled final answers.

Monte Carlo owns random sampling.

---

# 112. Scoring Engine contract

Event models do NOT assign FPL points.

Example:

Goal Model outputs:

```text
player scored 1 goal
```

Scoring Engine determines:

```text
GK/DEF/MID/FWD goal points
```

according to season config.

---

# 113. Rule-change safety

If FPL changes:

```text
defensive contribution thresholds
bonus system
goal points
clean-sheet points
```

football prediction models should ideally remain unchanged.

Only scoring/config layers should change unless the underlying target definition changes.

---

# 114. User-facing outputs

Eventually report:

```text
xG
xA
P(goal)
P(assist)
P(return)
P(clean sheet)
xSaves
P(defcon points)
xBonus
```

But `P(return)` is derived later from joint goal/assist simulations.

---

# 115. Return probability

Do NOT calculate naively:

```text
P(goal) + P(assist)
```

because:

```text
goal and assist events can overlap
```

Use Monte Carlo:

```text
P(return)
=
P(at least one goal or assist)
```

---

# 116. Blank probability

Likewise:

```text
P(blank)
```

should come from simulated FPL outcomes / defined return criteria.

Do not estimate independently unless used as a diagnostic model.

---

# 117. Haul probabilities

Final:

```text
P(8+)
P(10+)
P(15+)
```

must come from FPL point simulations, not Event Models.

---

# 118. Event uncertainty reporting

Recommended player fixture diagnostics:

```text
Goal expectation:
0.42 ± uncertainty

Assist expectation:
0.23 ± uncertainty

P(goal):
34%

P(assist):
20%
```

Uncertainty must feed sensitivity analysis.

---

# 119. Acceptance criteria

The Event Models layer is accepted when:

1. goals and assists are modelled separately from total FPL points,
2. team goals and player goals are coherent,
3. assists are linked to simulated goals,
4. penalties are separated from open-play xG,
5. set-piece hierarchy affects relevant events,
6. clean-sheet probability comes from team score process,
7. player CS eligibility incorporates minutes,
8. saves and goals conceded are approximately coherent,
9. defensive contributions are fixture-adjusted,
10. card probabilities are calibrated,
11. bonus is fixture-relative,
12. all event models support missing optional data,
13. all historical training is point-in-time safe,
14. probability outputs are calibrated,
15. complex models beat simple baselines before promotion,
16. all outputs are simulation-ready and versioned.

---

# 120. Codex implementation guidance

DO:

* implement event baselines first,
* preserve team/player coherence,
* separate open-play and penalties,
* link assists to goals,
* use minutes distributions,
* implement calibration tests,
* write probability-sum sanity checks,
* use season-specific scoring configuration downstream,
* keep models modular,
* expose uncertainty.

DO NOT:

* directly predict final FPL points,
* independently simulate every player goal with no team constraint,
* assume official assists equal FPL assists,
* independently predict clean sheets and opponent goals inconsistently,
* ignore substitution timing for clean sheets,
* hardcode scoring rules inside predictive models,
* use future lineups or target-match event data as features,
* add ML complexity without beating statistical baselines.

---

# 121. Final principle

The Event Models should answer:

```text
GIVEN THE TEAM ENVIRONMENT,
PLAYER ABILITY,
TACTICAL ROLE,
OPPONENT
AND POSSIBLE PLAYING TIME,

WHAT FOOTBALL EVENTS ARE LIKELY TO HAPPEN
TO THIS PLAYER IN THIS FIXTURE?
```

The output must be:

```text
PROBABILISTIC
CALIBRATED
COHERENT WITH THE MATCH
POINT-IN-TIME SAFE
SIMULATION READY
```

Only after these football events are simulated should the system ask:

```text
HOW MANY FPL POINTS DOES THIS OUTCOME PRODUCE?
```


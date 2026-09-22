# Player Talent Model Specification

## 1. Purpose

The Player Talent Model estimates the underlying football ability of a player independently from the quality of the team, league, tactical role and fixture context in which historical statistics were produced.

Its primary goal is to answer:

```text
HOW GOOD IS THIS PLAYER,
INDEPENDENTLY OF HIS CURRENT TEAM ENVIRONMENT?
```

The model must not assume that historical:

```text
xG/90
xA/90
goals/90
assists/90
```

will remain unchanged after:

* transfer to another club,
* transfer to another league,
* manager change,
* tactical role change,
* formation change,
* set-piece change.

Player Talent is an intermediate representation.

It is later combined with:

```text
Team Strength
Tactical Context
Minutes
Opponent Strength
Set Pieces
```

to create fixture-specific event rates.

---

# 2. Core principle

Separate:

```text
PLAYER ABILITY
```

from:

```text
TEAM ENVIRONMENT
```

Conceptually:

```text
observed_player_output
=
player_talent
× team_environment
× tactical_role
× opponent_context
× minutes
× stochastic_variance
```

The exact implementation does not have to use literal multiplication.

The important architectural rule is that the model must attempt to identify which part of historical production belongs to the player and which part belongs to the environment.

---

# 3. Example problem

A striker produces:

```text
0.35 npxG/90
```

for a team producing:

```text
1.20 xG per match
```

He transfers to a stronger club producing:

```text
2.00 xG per match
```

The model must NOT assume:

```text
future npxG/90 = 0.35
```

Instead, it should consider:

```text
historical share of team attacking output
historical shot volume
box touches
role
quality of new team
new tactical role
competition for chances
set pieces
minutes
```

The player's expected production may increase or decrease after the transfer.

---

# 4. Stable output contract

For every player at a prediction timestamp, return:

```text
player_id
prediction_timestamp

talent_npxg_per90
talent_xa_per90

talent_shots_per90
talent_shots_in_box_per90
talent_shots_on_target_per90

talent_big_chances_per90
talent_big_chances_created_per90
talent_key_passes_per90
talent_box_touches_per90

team_npxg_share
team_xa_share
team_shot_share
team_box_touch_share

finishing_component
creation_component
set_piece_attacking_component
defensive_contribution_rate

player_talent_uncertainty
sample_reliability

model_version
dataset_version
feature_version
```

Not every optional field must be available for every historical player.

Missing fields must remain explicit.

---

# 5. Do not predict FPL points here

This module must NOT predict:

```text
FPL points
captaincy
transfer recommendations
```

It must also not directly include future fixture difficulty.

Those belong downstream.

Player Talent should represent underlying player quality.

---

# 6. Primary historical inputs

Required where available:

```text
minutes_played
starts

expected_goals
non_penalty_expected_goals
expected_assists

shots
shots_in_box
shots_on_target

big_chances
big_chances_created
key_passes
touches_in_box

team_xg
team_xga

tactical_role
starting_position
team_id
competition_id
```

Optional:

```text
progressive_carries
progressive_passes
expected_threat
average_position
aerial_duels
set-piece data
```

---

# 7. Goals versus xG

Actual goals are useful but noisy.

The core attacking talent model should prefer:

```text
npxG
shots
shots in box
big chances
```

over raw goals.

Goals can still inform:

```text
finishing ability
```

but must be heavily regularized.

A player scoring:

```text
10 goals from 5 xG
```

should not automatically be assumed to have permanent elite finishing.

---

# 8. Assists versus xA

Actual assists are also noisy.

Creation talent should rely primarily on:

```text
xA
key passes
big chances created
set-piece involvement
```

Actual assists may be included as a weaker contextual signal.

---

# 9. Non-penalty xG

Use:

```text
npxG
```

as the primary open-play goal-threat signal.

Penalties must be handled separately.

Reason:

A player becoming or ceasing to be penalty taker can radically change xG without changing underlying open-play talent.

Therefore:

```text
open_play_goal_talent
```

and:

```text
penalty_role
```

must remain separate.

---

# 10. Set pieces

Player Talent should distinguish between:

```text
open-play creation talent
set-piece creation opportunity
```

and:

```text
penalty opportunity
```

Set-piece roles can change quickly.

They should therefore be primarily handled by Tactical Context / Set Piece Context.

Historical set-piece performance may still inform skill.

---

# 11. Per-90 normalization

Most historical attacking features should be normalized by playing time.

Examples:

```text
npxG_per90
xA_per90
shots_per90
box_touches_per90
key_passes_per90
```

However:

do not calculate unstable per-90 values from tiny samples without shrinkage.

Example:

```text
18 minutes
1 shot
```

must not imply a reliable:

```text
5 shots/90
```

---

# 12. Minimum sample handling

Every rate must have a reliability estimate.

Example:

```text
10 minutes -> extremely low reliability
300 minutes -> moderate
1500 minutes -> high
```

Use:

```text
Bayesian shrinkage
empirical Bayes
hierarchical priors
```

or another validated technique.

---

# 13. Shrinkage

Preferred concept:

```text
posterior_player_rate
=
weighted_observed_rate
+
weighted_population_prior
```

Players with small samples shrink more strongly toward:

```text
role average
position average
league average
```

Players with large samples rely more on their own history.

---

# 14. Appropriate priors

Priors should preferably depend on role.

Example groups:

```text
centre_forward
inside_forward
winger
attacking_midfielder
central_midfielder
wingback
fullback
centre_back
goalkeeper
```

A CB should not shrink toward the same attacking prior as a striker.

---

# 15. Multiple seasons

Use multiple historical seasons.

Do NOT simply average them equally.

Recent performance should generally receive more weight.

Recommended:

```text
exponential time decay
```

or:

```text
season-specific hierarchical weights
```

Candidate historical horizon:

```text
current season
previous season
2 seasons ago
3 seasons ago
```

Older data may remain useful for stable talent traits.

---

# 16. Different decay by feature

Not all skills should decay equally.

Potentially:

```text
minutes/role -> fast decay
shot volume -> medium decay
finishing ability -> slow decay
set-piece role -> very fast decay
```

Do not force one universal decay rate.

Backtest feature-group-specific decay.

---

# 17. Player team-share features

One of the most important components.

Calculate:

```text
player_npxg / team_npxg
player_xa / team_xa
player_shots / team_shots
player_box_touches / team_box_touches
```

Example:

Player X:

```text
0.30 npxG/90
```

may look mediocre.

But if his weak team creates only:

```text
1.0 xG/game
```

and he captures:

```text
30% of team npxG
```

his talent may be more impressive than raw output suggests.

---

# 18. Share stability

Team-share metrics may be more transferable between clubs than raw per-90 rates.

Test whether:

```text
team_npxg_share
team_xa_share
shot_share
```

predict future output after transfers better than absolute historical rates.

This must be validated empirically.

---

# 19. Team environment adjustment

Historical production should be adjusted for:

```text
team attack strength
team possession
team xG
team tactical dominance
opponent schedule strength
```

A player in Manchester City should not automatically receive a higher talent score simply because his team creates more chances.

---

# 20. Opponent adjustment

Historical statistics must account for opponent quality.

Example:

```text
0.50 xG/90
```

generated mostly against weak opponents should not be interpreted exactly like:

```text
0.50 xG/90
```

against elite defenses.

Use the Team Strength Model for opponent adjustment.

---

# 21. Transfer between clubs

A club transfer must trigger:

```text
regime_change_flag = true
```

Historical talent remains.

Historical environment changes.

Do not discard the player's past.

Instead:

```text
player talent -> retained
team environment -> replaced
role/context -> re-estimated
```

---

# 22. Transfer to stronger club

Potential effects:

```text
more team possession
more team xG
more box entries
more teammate quality
potentially fewer individual team shares
```

The model must not blindly apply:

```text
better club = higher player xG
```

because a player may receive a smaller share of a stronger attack.

---

# 23. Transfer to weaker club

Possible effects:

```text
lower team xG
higher individual attacking share
more responsibility
more set pieces
```

Again:

talent and environment must remain separate.

---

# 24. Cross-league transfer

Players arriving from other leagues require a league-strength adjustment.

Do not directly compare:

```text
0.70 xG/90 Eredivisie
```

to:

```text
0.70 xG/90 Premier League
```

without context.

---

# 25. League strength coefficient

Create a learned or empirically estimated:

```text
league_strength_coefficient
```

Potential method:

Use players who transferred between leagues.

For each transfer:

```text
pre-transfer metrics
post-transfer metrics
age
role
team strength
minutes
```

Estimate expected translation.

---

# 26. Translation model

Potential model:

```text
expected_PL_rate
=
f(
    previous_league_rate,
    previous_league_strength,
    previous_team_strength,
    new_team_strength,
    role,
    age,
    position
)
```

Candidate:

```text
hierarchical regression
CatBoost
Bayesian transfer model
```

---

# 27. Small cross-league samples

For obscure leagues or limited transfers:

shrink strongly toward a generic league-level prior.

Do not invent precise multipliers.

Uncertainty must increase.

---

# 28. Age

Player talent changes with age.

Potential nonlinear patterns:

```text
young players improving
prime years stable
older players declining
```

Age should be a contextual feature.

Avoid hardcoded rules such as:

```text
age > 30 = -10%
```

Use learned relationships.

---

# 29. Position and tactical role

FPL position alone is insufficient.

Example:

Two FPL MID players can actually play:

```text
DM
AM
LW
ST
```

Their expected attacking production differs enormously.

Use:

```text
tactical_role
```

as a major feature.

---

# 30. Role history

Maintain role over time.

Example:

```text
2025:
LW

2026:
ST
```

Historical LW matches remain informative about talent but should be downweighted for predicting ST-specific event rates.

---

# 31. Role-specific talent

Potentially estimate:

```text
player talent conditional on role
```

Example:

```text
Player X:
npxG/90 as LW
npxG/90 as ST
```

If sample permits.

Otherwise use hierarchical sharing across roles.

---

# 32. Formation context

Formation influences player role.

Examples:

```text
LB in 4-4-2
LWB in 3-4-3
```

must not be treated identically.

Formation should be consumed through Tactical Context.

---

# 33. Manager context

Managers influence:

```text
positional roles
chance creation
set pieces
pressing
attacking freedom
```

Manager changes should modify interpretation of recent data.

The Player Talent Model should not mistake:

```text
manager tactical effect
```

for:

```text
permanent talent change
```

---

# 34. Manager change weighting

After manager change:

```text
post-change data -> high relevance
pre-change data -> retained as talent evidence
```

But pre-change production should be downweighted when estimating current role-based production.

---

# 35. Injury effects

Long injuries may temporarily affect:

```text
physical output
shot volume
role
minutes
```

Immediately after return:

increase uncertainty.

Do not permanently lower talent because of a short low-minute return period.

---

# 36. Finishing talent

Finishing skill may exist but is difficult to estimate.

Potential feature:

```text
goals - xG
```

but use:

```text
multi-season sample
shrinkage
shot-quality context
```

Avoid trusting short-term finishing overperformance.

---

# 37. Finishing model

Potential structure:

```text
finishing_component
=
shrunk historical goals minus xG
```

with strong shrinkage toward:

```text
league/role average finishing
```

Only include if it improves future goal prediction.

---

# 38. Creation talent

Creation may be estimated using:

```text
xA
key passes
big chances created
progressive passes
set-piece share
```

Again:

separate open play from set pieces.

---

# 39. Touches in box

Useful for identifying attacking role and potential.

A rise in:

```text
box touches/90
```

after a role change may indicate genuine increased attacking opportunity before FPL points appear.

---

# 40. Shot quality

Do not use only shot count.

Consider:

```text
xG per shot
shots in box share
big chance share
```

Two players with 4 shots/90 can have very different goal threat.

---

# 41. Shot volume and shot quality

Potential decomposition:

```text
goal threat
=
shot volume
× average shot quality
× finishing component
```

This decomposition is interpretable and transferable.

---

# 42. Assist opportunity decomposition

Potentially:

```text
assist threat
=
chance creation volume
× average chance quality
× teammate finishing environment
```

Historical xA already captures part of this.

The model should avoid double counting.

---

# 43. Defensive talent

For defenders and midfielders, estimate:

```text
defensive_contribution_rate
```

using:

```text
tackles
interceptions
clearances
blocks
recoveries
```

But defensive contributions are also opponent-dependent.

Therefore:

Player Talent estimates the underlying rate.

Fixture Event Model adjusts it for opponent context.

---

# 44. Defender attacking talent

For defenders include:

```text
set-piece xG
open-play xG
xA
crossing creation
box touches
aerial threat
```

Centre backs and fullbacks should have different priors.

---

# 45. Goalkeeper talent

Goalkeepers require separate talent features.

Potential:

```text
save rate
post-shot xG prevented
penalty save history
cross claim ability optional
```

Player Talent Model may expose:

```text
goalkeeper_save_talent
```

for the Save Model.

---

# 46. Sample reliability output

For each talent estimate return:

```text
sample_reliability
```

Potential range:

```text
0 to 1
```

High reliability:

```text
large recent relevant sample
stable role
same league/team context
```

Low reliability:

```text
new signing
few minutes
new league
new role
long injury
```

---

# 47. Uncertainty

Return:

```text
player_talent_uncertainty
```

Uncertainty should rise with:

```text
small sample
cross-league transfer
role change
manager change
missing advanced data
long absence
young/new player
```

---

# 48. New players with no senior history

Use hierarchical priors.

Possible evidence:

```text
academy/minor league data if available
age
position
competition level
manual context
```

Never assign:

```text
0 attacking talent
```

because data is missing.

Use prior + high uncertainty.

---

# 49. New Premier League signing

Preferred sequence:

```text
cross-league history
↓
league adjustment
↓
previous-team adjustment
↓
new-team environment
↓
new tactical role
↓
fixture-specific model
```

---

# 50. Promoted-team players

A player promoted with his team is not a club transfer but environment changes substantially.

Flag:

```text
league_change
```

Use Championship history with Premier League translation.

---

# 51. Newly promoted team environment

Do not alter player talent just because:

```text
team expected goals decrease
```

That belongs primarily to Team Strength.

---

# 52. Time decay

Recommended general approach:

```text
exponential decay
```

but with feature-group-specific half-lives.

Candidate examples for testing:

```text
npxG rate:
90–180 days

xA rate:
90–180 days

role:
30–60 days

team share:
60–120 days

finishing:
365+ days
```

These are candidate ranges only.

Backtesting decides.

---

# 53. Match weighting by minutes

A 90-minute performance should generally carry more evidence than a 10-minute cameo.

Use exposure-aware weighting.

However:

do not completely discard substitute appearances.

---

# 54. Match weighting by role relevance

Historical match relevance may depend on role similarity.

Example:

Current role:

```text
ST
```

Historical:

```text
ST -> weight 1.0
LW -> weight 0.6
CM -> weight 0.2
```

Do not hardcode final values.

Learn or validate them.

---

# 55. Team-share normalization

For each match:

```text
player_npxg_share =
player_npxg /
team_npxg
```

Handle zero team npxG safely.

Likewise:

```text
player_xa_share
player_shot_share
player_box_touch_share
```

Use smoothing.

---

# 56. Player involvement

Create a broader attacking involvement representation.

Possible:

```text
weighted combination of:
npxG share
xA share
shot share
box touch share
```

This can help identify important players even before FPL returns occur.

---

# 57. Do not use recent FPL points as primary talent feature

Recent points may be retained as:

```text
baseline/reporting signal
```

but must not dominate Player Talent.

Reason:

FPL returns are noisy.

---

# 58. Penalty dependency

Calculate:

```text
penalty_xg_share
```

and:

```text
open_play_npxg_share
```

separately.

This allows immediate adjustment when penalty hierarchy changes.

---

# 59. Set-piece creation dependency

Similarly separate:

```text
open_play_xa
set_piece_xa
```

when data allows.

If unavailable:

use set-piece role as contextual correction.

---

# 60. Model candidates

Evaluate in increasing complexity.

## TAL-001

Simple rolling per-90 rates.

## TAL-002

Exponentially weighted per-90.

## TAL-003

Team-share adjusted rates.

## TAL-004

Empirical Bayesian shrinkage.

## TAL-005

Role-conditioned shrinkage.

## TAL-006

Opponent-strength adjusted rates.

## TAL-007

Transfer/team-environment adjustment.

## TAL-008

Cross-league translation.

## TAL-009

Hierarchical Bayesian talent model.

## TAL-010

CatBoost context correction.

Do not skip directly to TAL-010.

---

# 61. Preferred statistical core

Strong candidate:

```text
hierarchical empirical Bayes
```

for:

```text
npxG/90
xA/90
shot rate
```

Hierarchy may include:

```text
league
position
tactical role
player
```

This provides natural shrinkage.

---

# 62. Optional CatBoost layer

Use CatBoost only as:

```text
context adjustment
```

or:

```text
residual correction
```

after interpretable talent estimates exist.

Example:

```text
base talent npxG/90 = 0.38
CatBoost context correction = +0.04
```

Final:

```text
0.42
```

if validated.

---

# 63. Do not make CatBoost responsible for everything

Avoid:

```text
all raw stats -> future xG
```

without interpretable intermediate structure.

We want to know whether prediction changed because of:

```text
player talent
team environment
role
opponent
minutes
```

---

# 64. Cross-validation strategy

Use walk-forward temporal validation.

Example:

```text
train through date X
predict next fixtures
```

Do not random split player-match rows.

---

# 65. Transfer validation subset

Create a dedicated evaluation dataset:

```text
players who changed clubs
```

Compare:

```text
raw previous per90
team-adjusted model
cross-league model
```

on post-transfer performance.

This is critical.

---

# 66. Role-change validation

Create another evaluation subset:

```text
players with identified tactical-role changes
```

Check whether regime-aware model improves future prediction.

---

# 67. New-league validation

Evaluate players transferring:

```text
Bundesliga -> PL
La Liga -> PL
Serie A -> PL
Ligue 1 -> PL
Championship -> PL
other -> PL
```

Metrics should be grouped by source league where sample allows.

---

# 68. Evaluation targets

Evaluate future:

```text
npxG/90
xA/90
shots/90
box touches/90
```

over future horizons such as:

```text
next 3 matches
next 5 matches
next 10 matches
```

Do not judge only next-match variance.

---

# 69. Core metrics

For continuous talent estimates:

```text
MAE
RMSE
Poisson deviance where appropriate
Spearman rank correlation
```

For ranking:

```text
future top-decile identification
```

For transfer players:

```text
post-transfer prediction error
```

---

# 70. Calibration / reliability

Talent values are latent rates rather than probabilities.

Still validate reliability:

Players projected around:

```text
0.40 npxG/90
```

should average near that over sufficiently large future samples.

Use bins.

---

# 71. Baselines

Required:

```text
season-to-date per90
last-5 per90
exponentially weighted per90
previous-season per90
```

Advanced model must beat them.

---

# 72. Missing advanced data

System must degrade gracefully.

If only:

```text
xG
xA
minutes
team xG
```

are available:

Player Talent should still work.

Richer features improve quality but are not mandatory for operation.

---

# 73. Missing cross-league xG

If player arrives from a league without xG data:

possible fallback:

```text
goals
assists
minutes
position
team strength
competition prior
```

with much stronger shrinkage and uncertainty.

---

# 74. Data quality flags

Create:

```text
has_xg_data
has_xa_data
has_shot_data
has_role_data
has_cross_league_history
```

These may also inform uncertainty.

---

# 75. Data-source disagreement

If sources disagree materially:

```text
preserve both raw values
```

Canonical resolution must follow source priority rules.

Do not silently average arbitrary provider fields.

---

# 76. Outlier handling

Do not blindly delete outliers.

Extreme players can be real.

Use:

```text
robust statistics
shrinkage
distribution-aware models
```

Investigate suspicious provider errors separately.

---

# 77. Position change example

Player:

```text
previous season: winger
current season: striker
```

Historical winger data:

```text
still informs:
shot ability
creation ability
finishing
```

but current striker role should influence expected volume.

Player Talent remains relatively stable.

Player Fixture Rate changes substantially.

---

# 78. Full conceptual decomposition

Recommended:

```text
PLAYER TALENT
    ↓
role-independent underlying ability

+

TACTICAL CONTEXT
    ↓
current usage and role

+

TEAM STRENGTH
    ↓
available attacking environment

+

OPPONENT
    ↓
fixture difficulty

+

MINUTES
    ↓
playing-time exposure

=

PLAYER FIXTURE EVENT RATES
```

This separation is mandatory.

---

# 79. Fixture-specific rate model

Player Talent should NOT output:

```text
GW5 expected goals
```

It outputs latent rates.

`player_fixture_rate_model` later produces:

```text
fixture_npxG_per90
fixture_xA_per90
```

---

# 80. Example

Historical player talent:

```text
talent_npxG_per90 = 0.34
talent_xa_per90 = 0.21
```

Current context:

```text
new stronger club
ST role
penalty taker
weak opponent
```

Fixture model may produce:

```text
fixture_npxG_per90 = 0.52
fixture_penalty_xg_per90 = 0.12
fixture_xa_per90 = 0.18
```

These are different concepts.

---

# 81. Player latent finishing component

Optional output:

```text
finishing_component
```

Could represent expected deviation from average finishing.

Strong regularization required.

Do not allow this component to dominate expected goals.

---

# 82. Player latent creativity component

Optional:

```text
creation_component
```

representing ability to generate high-quality chances beyond team context.

Again:

test whether it improves future xA.

---

# 83. Player similarity priors

For low-sample players, potential prior can use similar players.

Similarity features:

```text
age
role
league
shot profile
creation profile
physical profile if available
```

This is optional advanced functionality.

---

# 84. Young breakout players

Time decay should allow rapid updates.

A young player whose role and production change dramatically should not remain anchored indefinitely to old low-volume history.

Use:

```text
regime detection
age interaction
recent evidence
```

with increased uncertainty.

---

# 85. Stable elite players

Large multi-season samples should prevent overreaction to:

```text
2 poor matches
```

This is a key benefit of shrinkage and long-term priors.

---

# 86. Player talent history

Store talent estimates over time.

Example:

```text
prediction_timestamp
player_id
talent_npxg_per90
talent_xa_per90
```

This allows analysis of:

```text
how the model's belief changed
```

---

# 87. Reproducibility

Every estimate must include:

```text
prediction_timestamp
training_cutoff
model_version
dataset_version
feature_version
```

---

# 88. Model artifact

Persist:

```text
model parameters
priors
role taxonomy
league coefficients
time decay settings
feature schema
training cutoff
```

---

# 89. Leakage rules

Forbidden for historical predictions:

```text
future transfer
future club
future role
future season aggregates
future xG
future minutes
future set-piece hierarchy
future manager information
```

Everything must be frozen as of:

```text
prediction_timestamp
```

---

# 90. Transfer timing

If a transfer is announced after prediction timestamp:

the player still belongs to his old context for that historical prediction.

Use temporal player-team spells.

---

# 91. Previous-season totals

Never use final previous/current season aggregates if they contain matches after historical prediction time.

Previous completed seasons are safe.

Current season must be season-to-date only.

---

# 92. Interaction with Team Strength

Player Talent receives historical Team Strength context.

It should use this to separate:

```text
player share
```

from:

```text
team volume
```

---

# 93. Interaction with Tactical Context

Tactical Context supplies:

```text
current role
role-change flag
formation
set pieces
manager regime
```

Player Talent uses this to weight relevant history.

---

# 94. Interaction with Minutes

Player Talent should use historical minutes for exposure normalization.

But future xMins comes from Minutes Model.

Do not make current talent depend directly on future expected minutes.

---

# 95. Interaction with Event Models

Goal/Assist models consume:

```text
fixture-adjusted talent rates
```

not raw historical xG/xA.

---

# 96. Interpretability

For each talent estimate, expose diagnostics.

Example:

```text
Player X talent_npxG_per90 = 0.38

Evidence:
recent PL npxG/90: 0.42
previous season npxG/90: 0.35
team-adjusted share: strong
role prior: ST
cross-league adjustment: none
small-sample shrinkage: -0.03

uncertainty: low
```

---

# 97. SHAP

If CatBoost is introduced:

generate SHAP diagnostics.

Do not rely solely on global feature importance.

---

# 98. Sensitivity

Downstream sensitivity engine should perturb:

```text
talent_npxg_per90
talent_xa_per90
```

according to `player_talent_uncertainty`.

New signings should generally receive wider perturbations.

---

# 99. Recommended initial production architecture

Implement:

```text
exponentially weighted per90
+
team-share adjustment
+
opponent adjustment
+
role-specific empirical Bayes shrinkage
+
transfer/regime weighting
+
cross-league adjustment
```

This is already part of final architecture.

Then test:

```text
hierarchical Bayesian implementation
CatBoost residual correction
```

only if beneficial.

---

# 100. Acceptance criteria

Player Talent Model is accepted when:

1. it separates talent from team environment,
2. historical rates are time-weighted,
3. small samples are shrunk,
4. role is explicitly represented,
5. penalties are separated from open-play talent,
6. transfers preserve player identity,
7. cross-league transfers receive explicit adjustment,
8. uncertainty increases for low-information players,
9. model beats simple per-90 baselines,
10. transfer-player backtests improve over raw previous-club rates,
11. role-change backtests show no systematic failure,
12. no future context leaks into historical estimates,
13. output contract is stable and reproducible.

---

# 101. Codex implementation guidance

DO:

* build simple rate baselines first,
* implement exposure-aware statistics,
* implement shrinkage,
* use team shares,
* keep open-play and set-piece production separate,
* build explicit cross-league adjustment,
* preserve uncertainty,
* test transfer cases separately,
* version all estimates.

DO NOT:

* use raw goals/assists as the main talent measure,
* assume xG/90 transfers unchanged between clubs,
* treat team quality as player talent,
* average all seasons equally,
* trust tiny per-90 samples,
* hardcode subjective league multipliers,
* discard historical data after a regime change,
* use future roles or transfers in historical predictions,
* make one opaque ML model responsible for every layer.

---

# 102. Final principle

The Player Talent Model should answer:

```text
WHAT WOULD THIS PLAYER'S UNDERLYING FOOTBALL ABILITY LOOK LIKE
IF WE SEPARATED HIM FROM THE SPECIFIC TEAM, LEAGUE AND TACTICAL ENVIRONMENT
THAT GENERATED HIS HISTORICAL NUMBERS?
```

The downstream system then determines:

```text
HOW THAT TALENT SHOULD TRANSLATE
IN THE PLAYER'S CURRENT TEAM,
CURRENT ROLE,
CURRENT FIXTURE
AND EXPECTED MINUTES.
```

The primary objective is:

```text
TRANSFERABLE, SHRUNK, CONTEXT-AWARE, OUT-OF-SAMPLE PLAYER TALENT ESTIMATION.
```

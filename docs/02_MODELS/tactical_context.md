# Tactical Context Engine Specification

## 1. Purpose

The Tactical Context Engine represents how a player's current role, manager, formation, club environment, set-piece responsibility and squad situation affect the interpretation of historical performance.

Its purpose is not to predict FPL points directly.

It provides context to:

* Player Talent Model,
* Minutes Model,
* Player Fixture Rate Model,
* Team Strength Model,
* Event Models.

The engine must answer:

```text
HOW IS THIS PLAYER CURRENTLY BEING USED,
AND HOW DIFFERENT IS THAT FROM THE CONTEXT
THAT GENERATED HIS HISTORICAL DATA?
```

---

# 2. Core principle

Historical player statistics are not equally relevant under every tactical context.

Example:

```text
Player X historical role:
LW

Current role:
ST
```

Historical data remains useful for estimating:

```text
finishing
shot quality
creation
general attacking talent
```

but historical:

```text
shot volume
box touches
xG/90
assist profile
```

may no longer transfer one-to-one.

Therefore Tactical Context modifies the interpretation and weighting of historical information.

---

# 3. Stable output contract

For every player at a prediction timestamp return:

```text
player_id
team_id
prediction_timestamp

current_tactical_role
role_confidence

current_primary_position
current_secondary_positions

dominant_team_formation
formation_confidence
formation_stability

manager_id
manager_regime_age_days
manager_regime_matches

club_change_flag
league_change_flag
manager_change_flag
formation_change_flag
role_change_flag
fpl_position_change_flag
set_piece_change_flag
injury_return_flag
squad_competition_change_flag

regime_change_types
regime_change_confidence

historical_weight_multiplier
current_role_multiplier_goal
current_role_multiplier_assist
current_role_multiplier_minutes
current_role_multiplier_defcon

penalty_role
direct_free_kick_role
indirect_free_kick_role
corner_role_left
corner_role_right

squad_competition_score
role_security_score

tactical_context_uncertainty

model_version
dataset_version
feature_version
```

---

# 4. Tactical role taxonomy

Do not rely only on provider position labels.

Create a canonical tactical-role taxonomy.

Suggested initial roles:

```text
goalkeeper

centre_back
wide_centre_back

defensive_fullback
balanced_fullback
attacking_fullback
wingback

defensive_midfielder
deep_playmaker
box_to_box_midfielder
central_midfielder
attacking_midfielder

touchline_winger
inside_forward
wide_playmaker

second_striker
centre_forward
target_forward
mobile_striker
false_nine
```

The taxonomy may evolve.

It must remain versioned.

---

# 5. FPL position versus tactical role

FPL position is separate from tactical role.

Example:

```text
FPL position:
MID

Tactical role:
centre_forward
```

This is highly relevant for FPL because the player receives midfielder scoring rules while being used as a striker.

Therefore both fields must be retained independently.

---

# 6. Role confidence

Every inferred tactical role should have:

```text
role_confidence
```

Range:

```text
0.0 – 1.0
```

Higher confidence when:

```text
same role over several recent starts
consistent provider position
stable formation
manual confirmation
average position supports role
```

Lower confidence when:

```text
new manager
new signing
multiple recent roles
limited minutes
formation instability
missing lineup data
```

---

# 7. Role inference

Preferred evidence order:

```text
manual context override
confirmed lineup position
recent starting positions
formation
average position
event profile
historical role
FPL position
```

FPL position should be weak evidence for real tactical role.

---

# 8. Role inference from event profile

If position data is incomplete, infer supporting evidence from statistics.

Examples:

High:

```text
box touches
shots
central attacking actions
```

may support:

```text
striker / inside forward
```

High:

```text
crosses
wide progression
chance creation
```

may support:

```text
winger / attacking fullback
```

This should be supporting evidence, not the only classifier.

---

# 9. Role history

Store tactical role over time.

Recommended structure:

```text
player_id
effective_from
effective_to
tactical_role
confidence
source
```

Do not overwrite past roles.

---

# 10. Role change detection

A role change may be detected when:

```text
current role != historical dominant role
```

and persists beyond a configurable threshold.

Potential thresholds:

```text
2 consecutive starts
3 of last 4 starts
manual confirmation
manager change + immediate new role
```

Thresholds must be configurable.

---

# 11. Avoid overreacting to one match

One emergency appearance at:

```text
LB
```

should not necessarily trigger permanent:

```text
role_change
```

Use:

```text
persistence
confidence
manual context
```

---

# 12. Formation representation

Store the team's formation for every fixture.

Canonical examples:

```text
4-3-3
4-2-3-1
4-4-2
3-4-3
3-4-2-1
3-5-2
5-4-1
```

Provider formations must be normalized.

---

# 13. Formation stability

Derived feature:

```text
formation_stability
```

Possible definition:

percentage of recent relevant matches using the current dominant formation.

Example:

```text
last 5:
4-3-3
4-3-3
4-3-3
4-2-3-1
4-3-3

formation_stability = high
```

---

# 14. Formation change

Trigger:

```text
formation_change_flag
```

when the team's dominant tactical structure changes materially.

Do not trigger on every small shape-label difference.

Example:

```text
4-3-3
vs
4-1-4-1
```

may be tactically similar depending on implementation.

Consider canonical formation families.

---

# 15. Formation families

Optional abstraction:

```text
back_four_single_striker
back_four_two_striker
back_three_wingbacks
back_three_two_attackers
```

This may help reduce provider noise.

---

# 16. Manager identity

Manager must be represented through:

```text
manager_id
```

with temporal manager-team spells.

Required derived fields:

```text
days_since_manager_change
matches_since_manager_change
manager_change_flag
```

---

# 17. Manager regime

A new manager creates a potential tactical regime change.

The engine should compare:

```text
pre-manager context
post-manager context
```

including:

```text
formation
roles
team xG
pressing style
possession
rotation
set pieces
```

---

# 18. Manager history

If the manager has prior historical data:

use it as a prior for:

```text
formation preferences
rotation behavior
substitution behavior
attacking style
defensive style
```

with shrinkage toward league averages.

Do not assume behavior transfers perfectly between clubs.

---

# 19. Manager regime uncertainty

Uncertainty should be high immediately after appointment.

Example:

```text
manager_regime_matches = 1
```

means very little evidence.

Reduce uncertainty as more matches accumulate.

---

# 20. Club transfer

A club transfer triggers:

```text
club_change_flag
```

Player identity remains unchanged.

Historical statistics remain attached to the player.

Tactical context resets partially.

---

# 21. Transfer context

After transfer evaluate:

```text
new team quality
new role
new competition
new manager
new formation
new squad competition
new set-piece hierarchy
```

Do not use a single generic:

```text
transfer multiplier
```

---

# 22. League change

If:

```text
previous_competition != current_competition
```

trigger:

```text
league_change_flag
```

This primarily informs:

```text
Player Talent uncertainty
cross-league adjustment
```

---

# 23. Player role after transfer

A player may have been:

```text
ST
```

in old club and become:

```text
LW
```

in new club.

The engine must not assume role continuity.

Initial new-club role may come from:

```text
preseason information
first lineups
manual context
manager history
squad structure
```

with high uncertainty.

---

# 24. Set-piece context

Represent separately:

```text
penalties
direct free kicks
indirect free kicks
left corners
right corners
```

Do not store generic:

```text
set_piece_taker = true
```

because responsibilities differ.

---

# 25. Set-piece hierarchy

For each type store:

```text
rank
confidence
effective_from
effective_to
```

Example:

```text
penalties:
1 Palmer
2 Enzo
```

---

# 26. Penalty role

Canonical output:

```text
penalty_role:
    rank
    confidence
```

A player becoming first-choice penalty taker should immediately affect Goal Model context.

Do not wait for rolling xG to adapt.

---

# 27. Penalty hierarchy uncertainty

Uncertainty is high when:

```text
new signing
previous taker left
multiple recent takers
manager change
no penalties recently
```

Expose confidence.

---

# 28. Corner roles

Track:

```text
corner_role_left
corner_role_right
```

because some players take corners only from one side.

This may affect assist expectation.

---

# 29. Direct free kicks

Track separately from indirect free kicks.

Direct free kick responsibility influences:

```text
goal probability
```

Indirect free kicks influence:

```text
assist probability
```

---

# 30. Set-piece change detection

Trigger:

```text
set_piece_change_flag
```

when:

```text
new primary taker
old taker unavailable
transfer
manager change
manual override
repeated recent evidence
```

---

# 31. Squad competition

The engine must model realistic competition for a player's tactical role.

Example:

A left winger does not equally compete with every midfielder in the squad.

Create:

```text
role_competitor_set
```

---

# 32. Competitor availability

For each credible competitor consider:

```text
availability
recent starts
recent minutes
role similarity
manager preference
```

---

# 33. Squad competition score

Output:

```text
squad_competition_score
```

Higher value:

```text
more credible alternatives
stronger alternatives
manager rotates role often
```

Lower value:

```text
player is clear first choice
competitors injured
no realistic alternatives
```

Exact scale can be:

```text
0–1
```

---

# 34. Role security score

Separate:

```text
role_security_score
```

Conceptually combines:

```text
start consistency
competition
manager trust
availability
tactical necessity
```

This feeds Minutes Model.

---

# 35. Injury return

Trigger:

```text
injury_return_flag
```

when a player recently returns from significant absence.

This affects:

```text
minutes uncertainty
role uncertainty
performance interpretation
```

---

# 36. Injury-return context

Store:

```text
days_since_return
matches_since_return
minutes_since_return
starts_since_return
```

Do not interpret low first-match production as immediate talent decline.

---

# 37. FPL position changes

Between seasons, FPL may reclassify a player.

Trigger:

```text
fpl_position_change_flag
```

This has major scoring implications.

It does NOT necessarily mean tactical role changed.

---

# 38. Regime-change types

Canonical values:

```text
club_change
league_change
manager_change
formation_change
tactical_role_change
fpl_position_change
set_piece_change
injury_return
squad_competition_change
```

Multiple may occur simultaneously.

---

# 39. Regime-change confidence

Return:

```text
regime_change_confidence
```

Example:

```text
manual confirmed role change = high
one unusual lineup = low
new manager + 4 consecutive new formations = high
```

---

# 40. Historical weighting

Core output:

```text
historical_weight_multiplier
```

This controls how much old data influences current-context estimates.

Example concept:

```text
stable role, stable manager:
1.0

new manager:
0.8

new club + new league + new role:
0.4
```

These are illustrative only.

Final values must be validated.

---

# 41. Do not delete old history

Regime changes modify weights.

Never:

```text
drop all matches before transfer
```

unless a specific model proves that beneficial.

Historical data still informs:

```text
finishing
creation
general talent
```

---

# 42. Different historical weights by feature

A regime change may affect different statistics differently.

Example:

New club:

```text
finishing ability -> old data still valuable
team xG share -> much less transferable
penalty role -> old data potentially irrelevant
minutes -> old data partially relevant
```

Therefore allow feature-group-specific weighting.

---

# 43. Role goal multiplier

Output:

```text
current_role_multiplier_goal
```

This represents how current role changes expected goal volume relative to latent talent.

It should be learned/validated.

Example:

```text
LW -> ST
```

may increase expected goal rate.

---

# 44. Role assist multiplier

Output:

```text
current_role_multiplier_assist
```

Example:

```text
CM -> AM
```

may increase creation volume.

---

# 45. Role minutes multiplier

Output:

```text
current_role_multiplier_minutes
```

Example:

A player used as:

```text
rotation winger
```

may have lower minutes than when used as:

```text
first-choice wingback
```

This feeds Minutes Model.

---

# 46. Defensive contribution multiplier

Output:

```text
current_role_multiplier_defcon
```

Example:

```text
DM
```

may generate more defensive actions than:

```text
AM
```

---

# 47. Role multipliers are contextual, not talent

Do not store them inside Player Talent.

Player Talent:

```text
underlying ability
```

Tactical Context:

```text
current opportunity/usage
```

---

# 48. Average position

If available, average position can support role inference.

Use carefully.

Do not treat average coordinates as perfect tactical truth.

Score state can distort positioning.

---

# 49. Event-profile role inference

Supporting features:

```text
shots
box touches
crosses
key passes
defensive actions
progressive carries
```

may help detect:

```text
more attacking role
more central role
deeper role
```

---

# 50. Formation and role interaction

The same provider position may mean different things.

Example:

```text
LB in 4-3-3
```

versus:

```text
LWB in 3-4-2-1
```

The engine must consider both position and formation.

---

# 51. Multi-role players

Some players legitimately switch roles frequently.

Do not force one permanent role.

Return:

```text
current_primary_position
current_secondary_positions
role_distribution optional
```

Example:

```text
ST: 0.60
RW: 0.30
LW: 0.10
```

---

# 52. Role distribution

Optional advanced output:

```text
P(role = ST)
P(role = LW)
...
```

This may feed simulation or sensitivity when tactical uncertainty is material.

---

# 53. Formation prediction

For future fixture, actual formation is unknown.

Use:

```text
recent dominant formation
manager formation history
opponent-specific tendencies
available personnel
```

to estimate:

```text
formation probability distribution
```

Optional advanced functionality.

---

# 54. Do not use future lineup

Historical backtests may not use:

```text
target-match actual formation
target-match actual position
target-match actual lineup
```

These are targets/outcomes.

Only pre-deadline information is allowed.

---

# 55. Tactical prediction mode

Default:

```text
pre_deadline
```

Optional future:

```text
post_lineup
```

These must remain separate.

---

# 56. Manual context importance

Because free data will sometimes miss nuanced tactical changes, manual context is a first-class component.

Example:

```yaml
player_id: ply_x
effective_from: 2026-09-01
context:
  tactical_role: centre_forward
  role_confidence: 0.90
reason: "Used centrally under new manager in last three starts."
```

---

# 57. Manual manager context

Example:

```yaml
team_id: team_x
effective_from: 2026-08-20
context:
  dominant_formation: "3-4-2-1"
  confidence: 0.85
```

---

# 58. Manual set-piece context

Example:

```yaml
player_id: ply_x
effective_from: 2026-09-05
context:
  penalty_rank: 1
  penalty_confidence: 0.95
```

---

# 59. Manual overrides are temporal

Every override must include:

```text
effective_from
effective_to
created_at
```

Historical backtest may only use override knowledge that was available before prediction time.

---

# 60. No retrospective tactical knowledge

Example:

After GW10 we realize player became striker in GW7.

We must NOT automatically use this knowledge in a backtest prediction made before GW7 unless that information was actually available then.

Point-in-time principle remains mandatory.

---

# 61. Tactical context uncertainty

Output:

```text
tactical_context_uncertainty
```

Increase for:

```text
new signing
new manager
unstable formation
multi-role player
missing lineup data
conflicting provider information
```

---

# 62. Interaction with Minutes Model

Minutes Model consumes:

```text
current_tactical_role
role_security_score
squad_competition_score
manager regime
formation stability
role change
```

Tactical Context must not directly output final xMins.

---

# 63. Interaction with Player Talent Model

Player Talent uses:

```text
historical_weight_multiplier
role relevance
regime changes
```

to decide how historical data should be weighted.

---

# 64. Interaction with Goal Model

Goal Model consumes:

```text
current_role_multiplier_goal
penalty role
direct free kick role
```

---

# 65. Interaction with Assist Model

Assist Model consumes:

```text
current_role_multiplier_assist
corners
indirect free kicks
```

---

# 66. Interaction with defensive contributions

Defensive Contribution Model consumes:

```text
current_role_multiplier_defcon
```

and opponent context.

---

# 67. Interaction with Team Strength

Team Strength may consume:

```text
manager regime
dominant formation
formation stability
```

but tactical context should not introduce circular dependencies.

---

# 68. Tactical role priors

Low-sample players should shrink toward role priors.

Example:

```text
new ST:
use historical ST distribution
```

with player's own prior talent.

---

# 69. Formation priors

New manager with one match:

do not assume formation is permanently established.

Use manager historical preference + club recent context.

---

# 70. New manager scenario

Example:

```text
old manager:
4-3-3

new manager:
3-4-2-1
```

Potential changes:

```text
fullback -> wingback
winger -> inside forward
CM -> double pivot
```

The engine should create regime flags for affected players.

---

# 71. Change detection should be conservative

False regime changes can cause model instability.

Prefer:

```text
under-react with uncertainty
```

over:

```text
dramatically rewrite all player rates after one match
```

---

# 72. Change-point detection

Optional advanced method:

Use statistical change-point detection on:

```text
average position
shot volume
box touches
team formation
role assignments
```

Possible methods:

```text
Bayesian change-point
CUSUM
ruptures library
```

Only introduce if useful.

---

# 73. Rule-based first implementation

Recommended first production architecture:

```text
temporal context records
+
rule-based regime detection
+
confidence scoring
+
manual override support
```

This is more interpretable than immediate ML.

---

# 74. Optional ML role classifier

Future option:

Input:

```text
formation
starting position
average coordinates
event profile
```

Output:

```text
tactical_role probabilities
```

Possible model:

```text
CatBoost
```

But manual/provider role data should exist first.

---

# 75. Optional role clustering

Alternative research approach:

Cluster player-match event profiles into tactical archetypes.

Do not make this a production dependency until validated.

---

# 76. Squad competition model

Possible initial approach:

```text
role competitor count
+
competitor recent start share
+
competitor availability
+
manager rotation rate
```

Output:

```text
0–1 competition score
```

Later ML may replace the heuristic if beneficial.

---

# 77. Player hierarchy inference

Infer squad hierarchy from:

```text
starts
minutes
substitution patterns
cup selection
league selection
manager regime
```

This feeds:

```text
role_security_score
```

---

# 78. Cup lineup information

Cup lineups provide tactical evidence.

Example:

Starter rested in cup:

```text
may imply strong PL role
```

Fringe player starts cup:

```text
may imply lower PL hierarchy
```

Use as contextual evidence, not deterministic truth.

---

# 79. European lineup information

Same principle.

European starts and rests can inform:

```text
hierarchy
rotation
current role
```

---

# 80. Team formation history

Store:

```text
team_id
fixture_id
manager_id
formation
```

Use only fixtures completed before prediction timestamp.

---

# 81. Set-piece history

Store every known set-piece event where possible.

Derived features:

```text
penalties_taken_last_n
corners_taken_last_n
free_kicks_taken_last_n
```

But hierarchy should update faster than long rolling history.

---

# 82. Confidence hierarchy

Manual confirmed evidence:

```text
highest confidence
```

Repeated lineup evidence:

```text
high
```

Single provider position:

```text
medium
```

Inferred event profile:

```text
lower
```

---

# 83. Conflict resolution

If:

```text
provider says RW
manual context says ST
```

manual context wins if:

```text
valid
time-safe
high confidence
```

But preserve provider raw data.

---

# 84. Provider disagreement

Never silently overwrite.

Store:

```text
source
source_value
canonical_value
resolution_method
confidence
```

---

# 85. Tactical context table

Recommended canonical table:

```text
fact_player_tactical_context
```

Fields:

```text
player_id
team_id
effective_from
effective_to

tactical_role
role_confidence

formation
manager_id

set_piece_roles

regime_flags
regime_confidence

squad_competition_score
role_security_score

source
created_at
```

---

# 86. Team regime table

Recommended:

```text
fact_team_tactical_regime
```

Fields:

```text
team_id
manager_id
effective_from
effective_to
dominant_formation
formation_stability
regime_confidence
```

---

# 87. Leakage rules

Forbidden:

```text
future formation
future lineup
future role
future transfer
future manager appointment
future set-piece hierarchy
future injury-return knowledge
```

All context must satisfy:

```text
effective_at <= prediction_timestamp
```

---

# 88. Backtesting

Walk-forward only.

For each historical prediction:

reconstruct tactical context from information available at that time.

This is more difficult than using today's hindsight but is mandatory.

---

# 89. Tactical baseline

Baseline:

```text
current role = most recent known starting role
current formation = most recent team formation
no regime weighting
```

Advanced engine must improve downstream predictions relative to this.

---

# 90. Evaluation

Tactical Context itself has multiple targets.

Potential:

```text
next-match starting role
next-match formation
next-match set-piece involvement
```

But most important evaluation is downstream:

```text
does tactical context improve:
xMins
future xG/xA
player EV
```

---

# 91. Role prediction metrics

If probabilistic role classifier exists:

```text
log loss
accuracy
macro F1
calibration
```

---

# 92. Formation prediction metrics

If predicting formation:

```text
accuracy
formation-family accuracy
probabilistic log loss
```

---

# 93. Regime-change evaluation

Evaluate players around:

```text
transfer
manager change
role change
```

Compare:

```text
with tactical context
vs
without tactical context
```

on future xG/xA/minutes.

---

# 94. Set-piece evaluation

Evaluate whether set-piece context improves:

```text
goal prediction
assist prediction
```

particularly after hierarchy changes.

---

# 95. Manual-context evaluation

Track how often manual context materially changes predictions.

Avoid creating a system that requires constant manual intervention.

Manual context should be:

```text
exception handling
```

not the primary source for every player.

---

# 96. Context freshness

Tactical context should be refreshed after:

```text
league match
cup match
European match
transfer
manager change
major injury
set-piece event
manual override
```

---

# 97. User-facing diagnostics

Optional output:

```text
Player: X
Role: ST
Role confidence: 91%

Recent change:
LW -> ST

Formation:
3-4-2-1

Set pieces:
Penalties #1
Corners none

Competition:
Low

Context uncertainty:
Medium
```

---

# 98. Explainability

For every major multiplier, record reason.

Example:

```text
goal role multiplier increased because:
- 3 consecutive starts as ST
- box touches increased
- average position became more central
```

No unexplained arbitrary multipliers.

---

# 99. Recommended initial implementation

Use:

```text
canonical temporal role records
manual override layer
formation normalization
manager spell tracking
rule-based regime detection
set-piece hierarchy
squad competition heuristic
confidence scoring
```

Then evaluate optional:

```text
ML role classifier
change-point detection
formation prediction
```

---

# 100. Acceptance criteria

Tactical Context Engine is accepted when:

1. tactical role is separate from FPL position,
2. roles are temporal,
3. manager regimes are temporal,
4. transfers preserve player identity,
5. formation changes can create regime flags,
6. role changes affect historical weighting,
7. set-piece hierarchy is represented explicitly,
8. squad competition feeds Minutes Model,
9. uncertainty is exposed,
10. manual overrides are versioned and time-safe,
11. no future tactical information leaks into backtests,
12. historical data is never deleted after regime changes,
13. output contracts are stable,
14. downstream models can consume context without provider-specific fields.

---

# 101. Codex implementation guidance

DO:

* implement canonical tactical role taxonomy,
* preserve temporal context history,
* normalize provider formations,
* support manual overrides,
* implement conservative regime detection,
* track manager spells,
* track set-piece hierarchy separately,
* expose confidence and uncertainty,
* write point-in-time tests.

DO NOT:

* use FPL position as tactical role,
* assume one formation permanently,
* infer permanent role from one match,
* delete history after transfer,
* hardcode subjective multipliers without validation,
* silently overwrite provider disagreement,
* use future lineups in historical predictions,
* make LLM interpretation mandatory for core functionality.

---

# 102. Final principle

The Tactical Context Engine should answer:

```text
WHAT HAS CHANGED ABOUT THE WAY THIS PLAYER OR TEAM IS CURRENTLY BEING USED,
AND HOW SHOULD THAT CHANGE THE RELEVANCE OF HISTORICAL DATA?
```

Its purpose is to convert raw historical performance into:

```text
CURRENT-CONTEXT-RELEVANT INFORMATION
```

without confusing:

```text
TACTICAL OPPORTUNITY
```

with:

```text
UNDERLYING PLAYER TALENT.
```

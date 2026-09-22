# FPL Decision Optimizer Specification

## 1. Purpose

The Decision Optimizer converts probabilistic player projections into actionable Fantasy Premier League decisions.

It is the final decision-making layer of the FPL Prediction & Decision Engine.

The optimizer must answer questions such as:

```text
Should I make a transfer?

Should I roll the free transfer?

Which player should I sell?

Which player should I buy?

Is a -4 hit worth taking?

What should my starting XI be?

What should my bench order be?

Who should be captain?

Who should be vice-captain?

Should I use Wildcard?

Should I use Free Hit?

Should I use Bench Boost?

Should I use Triple Captain?

What sequence of moves maximizes expected value over the next 6 Gameweeks?
```

The optimizer must always allow:

```text
DO NOTHING
```

as a valid decision.

---

# 2. Core principle

The optimizer does NOT predict football.

It consumes predictions from:

```text
Team Strength
Player Talent
Tactical Context
Minutes Model
Event Models
Monte Carlo
FPL Scoring
Projection Engine
```

and solves:

```text
WHAT ACTION SHOULD THE FPL MANAGER TAKE?
```

---

# 3. Separation of responsibilities

Prediction layer:

```text
What is likely to happen?
```

Optimization layer:

```text
Given those probabilities,
what is the best decision under FPL constraints?
```

These layers must remain separate.

---

# 4. Default planning horizon

Default:

```text
6 Gameweeks
```

Configuration:

```yaml
planning_horizon_gameweeks: 6
```

The horizon must be configurable.

Candidate horizons for backtesting:

```text
1
3
4
5
6
8
10
```

Six Gameweeks is the default operational horizon, not an unquestionable truth.

---

# 5. Horizon weighting

Initial candidate:

```text
GW+1 = 1.00
GW+2 = 0.95
GW+3 = 0.90
GW+4 = 0.85
GW+5 = 0.80
GW+6 = 0.75
```

Conceptually:

```text
weighted_EV =
Σ weight_gw × expected_points_gw
```

These weights must be configurable and tuned through historical backtesting.

---

# 6. Why future points are discounted

Future projections have higher uncertainty because:

```text
injuries may occur
prices may change
fixtures may move
roles may change
transfers may occur
future transfers provide flexibility
```

Therefore immediate points may receive more weight.

However:

do not over-discount future fixtures without evidence.

---

# 7. Stable optimizer input contract

Required:

```text
prediction_timestamp
current_gameweek
planning_horizon

current_squad
purchase_prices
selling_prices
current_prices
bank

free_transfers
available_chips

player_projections
fixtures
FPL_rules

model_versions
dataset_version
feature_version
```

Recommended additional inputs:

```text
player_projection_distributions
player_xmins
p_start
p_60_plus

projection_uncertainty

future_fixture_schedule
known_blank_gameweeks
known_double_gameweeks

chip_expiration
```

Optional:

```text
risk_preference
future_price_predictions
ownership
effective_ownership
rank_context
```

---

# 8. Current squad state

For each owned player store:

```text
player_id
team_id
position

purchase_price
current_price
selling_price

squad_slot
```

Do NOT reconstruct selling price using only current price if actual purchase price is available.

---

# 9. Selling price

FPL selling price differs from current market price when a player has risen since purchase.

The optimizer must use:

```text
selling_price
```

when calculating transfer affordability.

Never assume:

```text
selling_price = current_price
```

for owned players.

---

# 10. Transfer budget

After selling players:

```text
available_budget =
bank
+
sum(selling_prices_of_players_out)
```

New players cost:

```text
current_purchase_price
```

The resulting squad must remain affordable.

---

# 11. Squad constraints

Season rules must come from:

```text
docs/04_OPTIMIZER/fpl_rules.yaml
```

For 2026/27 the expected canonical squad structure is:

```text
15 players

2 GK
5 DEF
5 MID
3 FWD
```

Maximum:

```text
3 players from one Premier League club
```

These values must not be scattered as hardcoded constants throughout optimizer code.

---

# 12. Starting XI constraints

Starting XI:

```text
11 players
```

Required formation:

```text
1 GK

>= 3 DEF
>= 2 MID
>= 1 FWD
```

All other counts naturally follow from:

```text
11 total players
```

and squad composition.

---

# 13. Bench structure

Bench contains:

```text
1 substitute goalkeeper
3 outfield substitutes
```

For outfield bench:

```text
bench_position_1
bench_position_2
bench_position_3
```

order matters because of automatic substitutions.

---

# 14. Starting XI optimization

Do NOT simply select the 11 highest EV players.

Formation constraints may make that invalid.

Solve:

```text
maximize expected realized Gameweek points
```

subject to valid formation.

---

# 15. Automatic substitutions

The optimizer should account for automatic substitutions probabilistically.

Example:

```text
starter:
EV 5.0
P(appearance) 60%

bench player:
EV 4.2
P(appearance) 95%
```

Bench value is not zero.

The expected score should account for:

```text
starter DNP
→ eligible bench replacement
```

---

# 16. Bench optimization

Bench order should maximize expected realized points under automatic substitution rules.

Do not simply order bench players by raw EV.

Consider:

```text
P(starter DNP)
P(bench player appears)
formation eligibility
bench player's EV
```

---

# 17. Formation-sensitive autosubs

Example:

Starting XI has exactly:

```text
3 defenders
```

and one defender does not play.

A midfielder cannot replace that defender if doing so would result in:

```text
2 defenders
```

Therefore bench optimization must implement exact formation legality.

---

# 18. Goalkeeper substitution

Backup goalkeeper replaces starting goalkeeper only if:

```text
starting GK records zero playing time
```

and backup goalkeeper appears.

This should be simulated explicitly.

---

# 19. Scenario-based XI score

Preferred long-term approach:

Use aligned Monte Carlo samples.

For simulation `s`:

```text
determine which starters appear
apply automatic substitutions
apply formation constraints
calculate realized XI score
```

Then:

```text
Expected Team Score =
average(realized score across simulations)
```

This is better than summing independent player EVs.

---

# 20. Simplified XI baseline

Baseline:

```text
maximize sum(expected_points)
```

subject to formation constraints.

Advanced autosub-aware optimizer must be compared against this baseline.

---

# 21. Captain optimization

Captain must be selected from starting XI.

Baseline:

```text
captain =
player with highest expected points
```

---

# 22. Captain distribution

A more advanced captain optimizer should consider:

```text
EV
P(10+)
P(15+)
variance
floor
ceiling
P(appearance)
```

Default objective remains expected points unless a risk mode is explicitly selected.

---

# 23. Vice-captain optimization

Vice-captain matters if captain records zero minutes.

Therefore optimize:

```text
captain + vice-captain
```

jointly.

Expected captain multiplier should consider:

```text
P(captain appears)
P(captain DNP)
P(vice appears)
```

---

# 24. Vice-captain correlation

Do not automatically choose the second highest EV player.

Potentially consider correlated absence risk.

Example:

Two players from same fixture may have correlated postponement risk.

This is optional advanced functionality.

---

# 25. Captain objective

For risk-neutral optimization:

```text
maximize expected captain points
```

For optional risk-seeking mode:

```text
maximize EV + upside_component
```

For optional risk-averse mode:

```text
maximize EV - uncertainty_penalty
```

Risk modes must never replace default expected-value mode.

---

# 26. Transfer action space

Each Gameweek optimizer must include:

```text
0 transfers
1 transfer
2 transfers
...
```

up to rule/config limits.

Action:

```text
0 transfers
```

is always valid unless squad state itself is invalid.

---

# 27. Roll Free Transfer

Rolling a transfer has future value.

Therefore:

```text
NO TRANSFER
```

must not be evaluated as:

```text
0 immediate gain only
```

It also produces:

```text
additional transfer flexibility next GW
```

up to the maximum stored FT limit.

---

# 28. Free transfer state

For 2026/27:

```text
maximum stored FT = 5
```

State transition must be represented explicitly.

Conceptually:

```text
next_FT =
min(
    maximum_FT,
    remaining_FT_after_current_actions + next_GW_FT
)
```

Exact transition logic must follow season rules in `fpl_rules.yaml`.

---

# 29. Example FT transition

Current:

```text
3 FT
```

Use:

```text
1
```

Remaining:

```text
2
```

Next Gameweek receives one additional FT:

```text
3 FT
```

assuming no chip-specific rule changes the transition.

---

# 30. Rolling at cap

If current free transfers:

```text
5
```

and no transfer is made:

the manager cannot exceed:

```text
5
```

Therefore the marginal value of rolling is lower at the cap.

---

# 31. Transfer hit

Every transfer above the available free allowance incurs the season-specific hit cost.

For 2026/27:

```text
-4 points
```

per additional transfer.

Hit cost must come from configuration.

---

# 32. Gross versus net transfer gain

Always report:

```text
gross_expected_gain
transfer_cost
net_expected_gain
```

Example:

```text
Player A -> Player B

Gross 6GW gain:
+6.8

Hit:
-4.0

Net:
+2.8
```

---

# 33. Hit timing

A -4 cost occurs once.

Do not subtract:

```text
4 points per Gameweek
```

over the horizon.

Objective:

```text
multi_GW_gain - immediate_hit_cost
```

---

# 34. Break-even analysis

For every hit recommendation calculate:

```text
break_even_probability
```

or at minimum:

```text
expected_net_gain
```

A marginal:

```text
+0.2 expected points
```

hit should be treated as low confidence.

---

# 35. Transfer comparison

For every candidate transfer compare against:

```text
KEEP CURRENT PLAYER
```

not against zero.

Correct comparison:

```text
EV(new player)
-
EV(old player)
-
transfer cost
+
future squad effects
```

---

# 36. Opportunity cost

A transfer also consumes:

```text
one free transfer
```

which has future option value.

Therefore:

```text
transfer gain
```

is not only difference between two players' projected points.

---

# 37. Value of free transfer

The optimizer should learn/estimate:

```text
value_of_free_transfer
```

through multi-GW optimization.

Do not use an arbitrary permanent value such as:

```text
1 FT = 2 points
```

unless empirically derived.

---

# 38. Multi-transfer interactions

Two transfers can create value that neither can create individually.

Example:

```text
sell expensive player
↓
release budget
↓
upgrade second position
```

Therefore optimizer must evaluate combinations.

---

# 39. Transfer combinations

Do not greedily choose:

```text
best transfer #1
then best transfer #2
```

because the globally optimal pair may differ.

Use mathematical/combinatorial optimization.

---

# 40. Candidate player pruning

Full search space can be large.

Before optimization, safely prune obvious irrelevant candidates.

Possible candidate pool:

```text
top projected players by position
top value players
owned players
players near transfer-out threshold
set-piece specialists
high xMins players
```

Do not prune so aggressively that optimal solutions disappear.

---

# 41. Candidate pool size

Configurable.

Example research values:

```text
GK: top 10-20
DEF: top 30-50
MID: top 30-50
FWD: top 20-30
```

Final values should be chosen based on solver performance.

---

# 42. Primary optimizer method

Preferred:

```text
Mixed Integer Linear Programming
```

Candidate solvers:

```text
HiGHS
OR-Tools
```

Preferred free-first choice:

```text
HiGHS
```

through:

```text
scipy.optimize.milp
```

or direct compatible interface.

---

# 43. Why MILP

FPL has discrete decisions:

```text
player selected / not selected
transfer / no transfer
captain / not captain
chip / no chip
```

and linear constraints:

```text
budget
position counts
club limit
squad size
```

This naturally fits MILP.

---

# 44. Binary decision variables

Examples:

```text
squad[p] ∈ {0,1}

starter[p] ∈ {0,1}

captain[p] ∈ {0,1}

vice[p] ∈ {0,1}

transfer_in[p] ∈ {0,1}

transfer_out[p] ∈ {0,1}
```

---

# 45. Squad constraint

```text
Σ squad[p] = 15
```

---

# 46. Position constraints

```text
Σ GK = 2
Σ DEF = 5
Σ MID = 5
Σ FWD = 3
```

---

# 47. Club constraint

For every Premier League club:

```text
Σ squad[p from club] <= 3
```

unless historical rules for the target season specify otherwise.

---

# 48. Budget constraint

```text
cost_of_new_squad
<=
available_funds
```

Must correctly use:

```text
selling prices for owned outgoing players
current prices for incoming players
bank
```

---

# 49. Starting XI constraint

```text
Σ starter[p] = 11
```

and:

```text
starter[p] <= squad[p]
```

---

# 50. Starting formation constraints

```text
Σ starting GK = 1

Σ starting DEF >= 3

Σ starting MID >= 2

Σ starting FWD >= 1
```

---

# 51. Captain constraints

```text
Σ captain[p] = 1

captain[p] <= starter[p]
```

Vice-captain:

```text
Σ vice[p] = 1

vice[p] <= starter[p]
```

and:

```text
captain[p] + vice[p] <= 1
```

---

# 52. Transfer continuity

Without Wildcard/Free Hit:

```text
new_squad
=
old_squad
-
transfers_out
+
transfers_in
```

and:

```text
number transfers in
=
number transfers out
```

---

# 53. Maximum regular transfers

For 2026/27:

```text
20 transfers per Gameweek
```

outside Wildcard/Free Hit.

Keep this in season configuration.

This limit will rarely bind in normal optimization but must exist.

---

# 54. Objective function

Baseline risk-neutral objective:

```text
maximize:

weighted expected FPL points
-
transfer hit costs
```

over planning horizon.

---

# 55. Extended objective

Possible:

```text
Objective =
Σ_gw horizon_weight[gw] × expected_team_points[gw]

- transfer_hit_cost

+ terminal_squad_value

+ terminal_free_transfer_value

- optional_risk_penalty
```

Each optional component must be validated.

---

# 56. Terminal value problem

A six-GW optimizer must not behave as if:

```text
nothing exists after GW+6
```

Otherwise it may make strange final-horizon transfers.

Possible correction:

```text
terminal squad value
```

and:

```text
terminal FT value
```

---

# 57. Terminal player value

Potential:

```text
small weight × projected EV beyond horizon
```

or:

```text
next-GW expected value after horizon
```

Do not make terminal value dominant.

Backtest alternatives.

---

# 58. Receding horizon

Preferred operational strategy:

Every Gameweek:

```text
optimize next 6 GWs
execute only current decision
```

Then next Gameweek:

```text
update data
update projections
optimize again
```

This is:

```text
receding-horizon optimization
```

or model-predictive-control style planning.

---

# 59. Do not blindly execute future transfers

Future optimizer path is a:

```text
PLAN
```

not a commitment.

Only current-GW recommendation is actionable.

Future actions will be recalculated when new information arrives.

---

# 60. Future transfer plan

Still expose:

```text
GW4: roll
GW5: possible A -> B
GW6: possible C -> D
```

to show why a current roll or transfer is attractive.

---

# 61. Planning state

At every horizon step track:

```text
squad
bank
purchase prices
selling prices approximation
free transfers
chips remaining
```

---

# 62. Future prices

Future player prices are uncertain.

Default production planning should assume:

```text
current prices remain constant
```

unless a validated price model exists.

This assumption must be explicit.

---

# 63. Do not invent future prices

Never assume arbitrary:

```text
+0.1 next week
```

because a player is popular.

Optional Price Change Model may be added later.

---

# 64. Future selling prices

Because future price changes are uncertain, terminal selling values should not be treated as precise.

Default:

```text
use current price state
```

through the planning horizon.

---

# 65. Team value

Maximizing team value is NOT the main objective.

Primary objective:

```text
FPL points
```

Price/value enters as a constraint and optional flexibility signal.

---

# 66. Value metric

`EV per £m` is useful for candidate analysis.

But optimizer should not maximize:

```text
EV / price
```

directly.

A £15m player with huge EV may be optimal despite worse EV/£ than a cheap player.

---

# 67. Wildcard

Wildcard permits:

```text
unlimited permanent transfers
```

for the active Gameweek.

All squad constraints still apply.

---

# 68. Wildcard optimization

Wildcard optimization should construct the optimal:

```text
15-player squad
```

not merely identify transfers from current team.

Objective:

```text
maximize multi-GW value
```

subject to:

```text
budget
position constraints
club constraints
```

---

# 69. Wildcard baseline

Compare:

```text
best wildcard squad
```

against:

```text
best non-wildcard path
```

The difference represents:

```text
Wildcard value
```

---

# 70. Wildcard opportunity cost

Using WC now means:

```text
it cannot be used later in the same chip period
```

Therefore:

```text
current WC gain
```

must ideally be compared with estimated future chip option value.

---

# 71. Two chip sets

For 2026/27:

```text
one WC
one FH
one BB
one TC
```

are available in each half of the season.

Total:

```text
8 chips
```

The first set expires before the Gameweek 19 deadline and does not carry into the second half.

These dates/periods belong in:

```text
fpl_rules.yaml
```

---

# 72. Chip expiration pressure

Near chip expiration:

unused chip value tends toward:

```text
zero after expiration
```

Therefore optimizer should account for:

```text
use it or lose it
```

dynamics.

---

# 73. Only one chip per Gameweek

Constraint:

```text
Σ chips_used_in_GW <= 1
```

---

# 74. Free Hit

Free Hit creates a temporary squad for one Gameweek.

After the Gameweek:

```text
original squad returns
```

according to FPL rules.

---

# 75. Free Hit optimizer

Construct temporary optimal squad for:

```text
target Gameweek only
```

subject to:

```text
budget
position structure
club limits
```

The post-GW persistent squad state remains based on pre-FH squad.

---

# 76. Free Hit value

Compare:

```text
optimal FH score
```

against:

```text
best normal-action score
```

plus future consequences.

Free Hit should be particularly useful for:

```text
Blank Gameweeks
unusual Double Gameweeks
```

but the optimizer must decide based on EV rather than hardcoded strategy.

---

# 77. Free Hit restrictions

Season configuration must represent:

```text
unavailable in GW1
cannot be played in consecutive Gameweeks
```

for 2026/27.

Do not hardcode these assumptions into solver logic.

---

# 78. Free transfers and Free Hit

The free-transfer state interaction with Free Hit must follow official season rules.

For 2026/27, previously stored free transfers remain available after the chip according to the game's chip mechanics, while the Gameweek's received transfer is consumed as part of activation.

Represent this with explicit state-transition rules in `fpl_rules.yaml`.

Do not approximate it ad hoc.

---

# 79. Bench Boost

Bench Boost causes:

```text
all 15 squad players
```

to contribute points for that Gameweek.

---

# 80. Bench Boost optimization

BB value depends on:

```text
bench EV
bench xMins
fixture quality
team structure
```

Calculate:

```text
BB incremental EV =
expected 15-player score
-
expected normal XI/autosub score
```

---

# 81. Bench Boost interaction with transfers

Optimizer may recommend transfers before BB to improve bench quality.

But this must account for:

```text
transfer costs
future squad quality
```

Do not buy poor long-term assets solely for tiny BB gain.

---

# 82. Triple Captain

Triple Captain changes captain multiplier from:

```text
2x
```

to:

```text
3x
```

Incremental TC value is approximately one additional captain score relative to normal captaincy.

---

# 83. Triple Captain optimization

For every candidate GW:

```text
TC incremental EV =
expected captain score
```

above normal captain scoring.

But compare:

```text
future TC opportunities
```

before recommending use.

---

# 84. TC and Double Gameweeks

DGW often produces strong TC opportunities.

However:

do NOT hardcode:

```text
always TC in DGW
```

because:

```text
minutes risk
fixture quality
player quality
future opportunities
```

matter.

---

# 85. Chip horizon

Normal planning horizon is 6 GWs.

Chip analysis may need a longer horizon.

Example:

```text
Wildcard expires in GW19
current GW = 10
```

A six-GW horizon would not see expiration.

Therefore chip planner may use:

```text
extended chip horizon
```

up to the chip expiry boundary.

---

# 86. Chip planner

Recommended architecture:

```text
core squad optimizer
+
chip timing planner
```

Chip planner evaluates candidate Gameweeks using cached squad/fixture projections.

---

# 87. Chip combinatorial complexity

Evaluating all:

```text
WC
FH
BB
TC
```

sequences over many GWs can explode combinatorially.

Use:

```text
dynamic programming
beam search
scenario pruning
```

rather than brute force when necessary.

---

# 88. Optimizer hierarchy

Recommended architecture:

```text
LEVEL 1
Per-GW lineup/captain optimization

LEVEL 2
Transfer optimization

LEVEL 3
Multi-GW transfer planning

LEVEL 4
Chip timing optimization

LEVEL 5
Sensitivity / robustness analysis
```

---

# 89. Multi-GW algorithm

Candidate methods:

```text
MILP
dynamic programming
beam search
hybrid MILP + beam search
```

Preferred likely architecture:

```text
MILP for squad/lineup decisions

+

beam search / dynamic programming
for temporal transfer paths
```

Final choice must be benchmarked.

---

# 90. Why pure full-horizon MILP may be difficult

Multi-GW state includes:

```text
selling prices
FT state
chips
temporary FH squad
captain
bench
```

which can make one giant MILP complex.

A hybrid sequential approach may be easier and more maintainable.

---

# 91. Beam search

State:

```text
squad
bank
FT
chips
cumulative objective
```

At each GW:

generate top candidate actions.

Retain:

```text
best N states
```

based on objective + upper-bound estimate.

---

# 92. Beam width

Configurable:

```text
25
50
100
250
500
```

Test whether recommendations converge as width increases.

---

# 93. State deduplication

Different transfer paths may produce identical:

```text
squad
bank
FT
chips
```

Keep only the best state.

This drastically reduces search space.

---

# 94. Dominance pruning

State A dominates B when A has:

```text
same squad
>= bank
>= FT
same chips
>= cumulative EV
```

B can be discarded.

---

# 95. Transfer candidate generation

For each owned player:

identify plausible replacements based on:

```text
position
affordability
future EV
```

Do not consider every possible replacement if clearly dominated.

---

# 96. Transfer-out candidates

Potential pruning:

```text
lowest projected owned players
injured/suspended players
low xMins
poor future fixtures
players blocking high-value moves
```

But always allow current squad to remain unchanged.

---

# 97. Transfer-in candidates

Include:

```text
high total EV
high EV/£
high xMins
high fixture upside
premium options
budget enablers
```

---

# 98. No ownership bias by default

Do not optimize based on:

```text
ownership
```

by default.

Expected points should drive decisions.

Ownership may be used in optional rank/risk strategy mode.

---

# 99. Effective ownership

Optional advanced tournament/rank context.

If objective changes from:

```text
maximize expected FPL points
```

to:

```text
maximize probability of rank target
```

effective ownership may matter.

Keep this separate from default optimizer.

---

# 100. Default optimization personality

Default:

```text
risk-neutral expected-points maximization
```

No arbitrary:

```text
differential hunting
template avoidance
```

---

# 101. Optional risk modes

Possible configuration:

```text
risk_neutral
risk_averse
risk_seeking
```

But the UI/output must clearly state when non-EV mode is active.

---

# 102. Risk-adjusted objective

Possible:

```text
risk_averse:

EV - λ × variance
```

or:

```text
EV - λ × downside_risk
```

---

# 103. Upside objective

Possible:

```text
EV + λ × P(haul)
```

but only for explicit risk-seeking mode.

---

# 104. Rank-aware objective

Optional future:

simulate manager score relative to field/ownership.

Optimize:

```text
P(reach target rank)
```

rather than raw expected points.

This is advanced and not required for initial production system.

---

# 105. Expected value remains primary

All main development/backtesting should use:

```text
expected FPL points
```

because it provides an objective benchmark.

---

# 106. Projection uncertainty

Optimizer should consume:

```text
projection_uncertainty
minutes_uncertainty
```

for robustness analysis.

A transfer with:

```text
+0.5 projected points
```

but huge uncertainty should not be reported as strong recommendation.

---

# 107. Sensitivity engine

For each decision:

perturb projections using model uncertainty.

Re-run optimizer:

```text
hundreds of times
```

Candidate default:

```text
500
```

---

# 108. Recommendation confidence

Example:

Transfer A -> B selected in:

```text
462 / 500
```

sensitivity runs.

Then:

```text
selection_frequency = 92.4%
```

This indicates high stability.

---

# 109. Confidence categories

Candidate:

```text
HIGH >= 80%

MEDIUM 60-79.99%

LOW < 60%
```

Thresholds remain configurable.

---

# 110. Decision margin

Report difference between:

```text
best action objective
```

and:

```text
second-best action objective
```

Example:

```text
Best:
Roll FT

Objective:
44.2

Second:
A -> B

Objective:
44.0

Decision margin:
0.2
```

This should be considered marginal.

---

# 111. Do not force certainty

If two decisions are statistically indistinguishable:

output:

```text
MARGINAL DECISION
```

rather than pretending one is clearly superior.

---

# 112. Alternative actions

Always retain top alternatives.

Recommended:

```text
top 3-5 actions
```

with:

```text
net EV
transfer cost
future EV
confidence
```

---

# 113. Example output

```text
Recommended:
ROLL FT

6GW weighted EV:
281.4

Alternative:
Saka -> Palmer

6GW weighted EV:
281.0

Difference:
+0.4 for rolling

Confidence:
62%

Interpretation:
Marginal.
```

---

# 114. Transfer recommendation output

For each transfer:

```text
player_out
player_in

cost_in
selling_price_out

bank_before
bank_after

FT_before
FT_after

gross_gain_GW1
gross_gain_3GW
gross_gain_6GW

hit_cost
net_gain

recommendation_confidence
```

---

# 115. Squad output

Return:

```text
15-player squad
starting XI
bench goalkeeper
bench order 1-3
captain
vice-captain
```

---

# 116. Multi-GW output

Return:

```text
current action

planned actions GW+1...GW+5

expected score each GW

cumulative EV

FT trajectory

bank trajectory

chip trajectory
```

Future actions must be marked:

```text
PROVISIONAL
```

---

# 117. Reasons layer

Optimizer itself should return structured reason codes.

Example:

```text
TRANSFER_GAIN
MINUTES_RISK
FIXTURE_SWING
ROLL_FLEXIBILITY
BUDGET_UNLOCK
CHIP_PREPARATION
```

LLM/UI may translate these into natural-language explanations.

---

# 118. No LLM inside solver

LLM must not decide:

```text
which transfer is mathematically optimal
```

Core decision comes from deterministic optimizer.

LLM may explain results afterward.

---

# 119. Backtesting optimizer decisions

Historical replay:

At historical deadline:

```text
rebuild historical squad state
use historical pre-deadline projections
optimize
```

Then compare recommendation with realized future points.

---

# 120. Important backtest distinction

Do not judge one decision solely by:

```text
what happened once
```

Example:

Optimizer picks player with:

```text
70% better expected outcome
```

who then blanks.

That does not automatically make the decision wrong.

Evaluate many historical decisions.

---

# 121. Optimizer evaluation metrics

Track:

```text
average realized points
average expected points

points over no-transfer baseline

points over greedy 1GW optimizer

points over simple 6GW EV optimizer

hit efficiency

FT rolling efficiency

captain points

chip incremental points
```

---

# 122. No-transfer baseline

Critical baseline:

```text
keep squad
roll FT
optimize XI/captain only
```

Every transfer strategy must beat this over many historical periods.

---

# 123. Greedy baseline

Baseline:

```text
choose transfer with highest next-GW EV gain
```

The 6GW optimizer should ideally outperform it.

---

# 124. Simple multi-GW baseline

Baseline:

```text
choose transfer maximizing 6GW player EV difference
```

without:

```text
FT option value
future transfer sequence
chips
```

Compare advanced optimizer against it.

---

# 125. Captain baseline

Compare captain optimizer against:

```text
highest player EV
```

If advanced risk logic does not improve objective, retain simple rule.

---

# 126. Bench baseline

Compare against:

```text
bench sorted by individual EV
```

Measure autosub-aware improvement.

---

# 127. Chip baseline

Compare chip planner with simple heuristics such as:

```text
TC highest projected captain DGW

BB highest bench EV GW

FH biggest blank count

WC largest squad EV gap
```

Advanced method must justify additional complexity.

---

# 128. Walk-forward optimizer backtest

Never optimize using future projections generated with hindsight.

For historical GW:

```text
features <= historical deadline
projections generated as of deadline
optimizer state as of deadline
```

Then advance.

---

# 129. Historical squad state

To backtest actual manager decisions, store:

```text
squad
bank
purchase price
selling price
FT count
chips remaining
```

at every GW.

---

# 130. Synthetic squad backtesting

Also test on many generated historical squad states.

Why:

A single real manager's squad gives too few decision scenarios.

Generate valid squads with varying:

```text
team value
FT count
injuries
chip availability
```

---

# 131. Hit evaluation

Measure:

```text
realized gain from hits
expected gain at decision time
```

by forecast-margin buckets.

Example:

```text
predicted net gain 0-1
1-2
2-4
4+
```

This can determine whether small projected hits are systematically overconfident.

---

# 132. Minimum recommendation threshold

Do not necessarily execute every positive expected-value transfer.

Potential requirement:

```text
net_gain > threshold
```

where threshold accounts for:

```text
model error
FT option value
```

Threshold must be learned from backtesting.

---

# 133. Transfer inertia

A modest transfer threshold may prevent overtrading.

But do not arbitrarily set:

```text
must gain 2 points
```

without evidence.

---

# 134. Roll FT as explicit action

The solver should literally produce an action:

```text
ROLL_FT
```

not infer it from absence of transfer output.

This makes backtesting and explanations clearer.

---

# 135. Injury emergency

If owned player has:

```text
P(appearance) ≈ 0
```

optimizer still compares:

```text
sell
vs
bench
vs
roll
```

because bench strength and future recovery matter.

Do not hardcode:

```text
injured = automatic sell
```

---

# 136. Suspended player

Same principle.

One-match suspension may not justify transfer if:

```text
strong bench
excellent future fixtures
```

---

# 137. Fixture swing

The multi-GW optimizer naturally captures fixture swings.

Do not add arbitrary:

```text
good fixtures +3
```

heuristics.

Player projections already contain fixture effects.

---

# 138. Double Gameweeks

DGW projections should enter naturally as higher total Gameweek EV.

Optimizer may then:

```text
transfer players in
captain
use chips
```

if worthwhile.

No separate arbitrary DGW bonus.

---

# 139. Blank Gameweeks

Players without fixtures have:

```text
0 fixture EV
```

for that GW.

Optimizer can decide:

```text
bench
transfer
Free Hit
```

based on multi-GW consequences.

---

# 140. Fixture uncertainty

If future DGW/BGW fixture scheduling is uncertain:

do not treat an unconfirmed fixture as guaranteed.

Future advanced approach:

```text
fixture scenario probabilities
```

---

# 141. Fixture scenarios

Example:

```text
70% fixture moves into GW34
30% remains elsewhere
```

Run optimizer over scenario-weighted schedule.

Only if reliable probability estimates exist.

---

# 142. Current implementation

Use only:

```text
confirmed / known schedule as of prediction_timestamp
```

for standard optimization.

Potential future schedule changes may be shown separately.

---

# 143. Price-change planning

Optional future model.

Could estimate:

```text
P(+0.1)
P(-0.1)
```

before next deadline.

Do not include until validated.

---

# 144. Early transfer risk

Even if expected price rise exists, early transfer introduces:

```text
injury risk
European match risk
new information risk
```

Future transfer-timing optimizer may model this.

Not required initially.

---

# 145. Transfer timing

Default optimizer decision is intended for:

```text
near-deadline execution
```

unless explicitly running an early-transfer analysis.

---

# 146. Solver deterministic behavior

Given identical:

```text
inputs
rules
objective
```

optimizer must return identical solution.

Tie-breaking must be deterministic.

---

# 147. Tie-breaking

When equal objective solutions exist, candidate tie-breakers:

```text
fewer transfers
higher bank
more FT retained
lower projection uncertainty
lower squad cost
```

Order must be configured.

Recommended default:

```text
1. fewer paid transfers
2. more free transfers retained
3. greater bank flexibility
4. lower uncertainty
```

---

# 148. Avoid transfer churn

If two squads have effectively equal objective:

prefer:

```text
fewer transfers
```

This naturally reduces unnecessary churn.

---

# 149. Numerical tolerance

MILP solutions may differ by tiny values.

Define:

```text
objective_tolerance
```

Example candidate:

```text
0.01 expected points
```

Do not treat microscopic differences as meaningful.

---

# 150. Solver timeout

Configure:

```text
solver_time_limit
```

For production, if exact optimum is not found:

return best feasible solution plus:

```text
optimality_gap
```

Never silently pretend approximate result is exact.

---

# 151. Solver metadata

Record:

```text
solver
solver_version
solve_time
status
objective
optimality_gap
candidate_count
```

---

# 152. Optimization run metadata

Persist:

```text
optimization_run_id

prediction_timestamp
current_gameweek

projection_run_id
simulation_run_id

optimizer_version
fpl_rules_version

planning_horizon
horizon_weights

solver_metadata
```

---

# 153. Reproducibility

Any historical recommendation must be reproducible from:

```text
data version
model versions
simulation version
optimizer version
rules version
squad state
```

---

# 154. Invalid state detection

Before optimization validate:

```text
squad size
position counts
club counts
bank
prices
FT state
chip state
```

If inconsistent:

fail explicitly.

---

# 155. Do not silently repair squad

If user state is invalid due to data mismatch:

do not automatically:

```text
delete player
add cheapest player
```

Report the inconsistency.

---

# 156. Current FPL API squad state

When operating on user's real team, fetch canonical current state including:

```text
players
purchase prices
selling prices
bank
FT
chips
```

Never infer critical financial state where direct data exists.

---

# 157. Scenario optimization

Monte Carlo enables optional scenario-based optimization.

Objective:

```text
maximize average team score across scenarios
```

instead of:

```text
sum individual EV
```

This can capture:

```text
autosubs
captain fallback
player correlations
```

---

# 158. Scenario reduction

Using all:

```text
10,000 simulations
```

inside MILP may be expensive.

Potential:

```text
scenario clustering
sample 100-500 representative scenarios
```

or use expected values for transfers and full samples for final lineup/captain evaluation.

---

# 159. Recommended initial production approach

Use:

```text
EXPECTED VALUE
```

for:

```text
multi-GW transfer optimization
```

and Monte Carlo scenarios for:

```text
XI
bench
captain
sensitivity
```

This balances realism and computational cost.

---

# 160. Robust optimization

Future advanced option:

maximize performance under multiple plausible projection states.

Example:

```text
expected scenario
pessimistic xMins
optimistic xMins
```

Potentially useful for Wildcard.

Only add if sensitivity analysis shows value.

---

# 161. Diversification

Do not impose arbitrary:

```text
must spread players across teams
```

constraint.

FPL itself already limits:

```text
3 per club
```

If triple-up is optimal, optimizer may choose it.

---

# 162. Correlation-aware squad construction

Optional risk-aware optimization may consider correlated outcomes.

Example:

```text
GK + DEF same club
```

have positively correlated clean-sheet returns.

This can increase:

```text
variance
```

but does not necessarily reduce EV.

Default risk-neutral optimizer should not penalize correlation.

---

# 163. Stacking attackers

Same principle.

Two attackers from a strong team may be positively correlated.

No arbitrary anti-stack constraint.

---

# 164. Captain and ownership

Default captain ignores ownership.

Rank-aware mode may consider:

```text
effective ownership
```

but must be explicitly selected.

---

# 165. Recommendation confidence

Final recommendation confidence should combine:

```text
sensitivity selection frequency
decision margin
projection completeness
model uncertainty
```

Do not reduce confidence to one arbitrary formula without validation.

---

# 166. Structured recommendation contract

Return:

```text
recommended_action_type

transfers_out
transfers_in

hit_cost

starting_xi
bench_order
captain
vice_captain

chip

expected_points_GW1
expected_points_3GW
expected_points_6GW
weighted_objective

gross_gain
net_gain

FT_before
FT_after

bank_before
bank_after

recommendation_confidence
decision_margin

alternative_actions

provisional_future_plan
```

---

# 167. Recommendation action types

Canonical:

```text
ROLL_FT
TRANSFER
MULTI_TRANSFER
HIT
WILDCARD
FREE_HIT
BENCH_BOOST
TRIPLE_CAPTAIN
NO_ACTION_REQUIRED
```

---

# 168. Example transfer recommendation

```text
Action:
TRANSFER

OUT:
Player A

IN:
Player B

Cost:
0 points

GW+1 gain:
+1.1

3GW gain:
+3.8

6GW gain:
+5.7

Weighted gain:
+4.9

FT after deadline:
2

Confidence:
84%
```

---

# 169. Example roll recommendation

```text
Action:
ROLL_FT

Immediate transfer best alternative:
+0.3 expected points

Value of additional future flexibility:
higher than immediate gain

Confidence:
78%
```

---

# 170. Example hit recommendation

```text
Action:
2 transfers

Gross 6GW gain:
+7.3

Hit:
-4

Net:
+3.3

Sensitivity selection frequency:
86%

Recommendation:
Take hit
```

---

# 171. Example marginal decision

```text
Roll FT objective:
45.31

Transfer objective:
45.36

Difference:
0.05

Confidence:
51%

Recommendation:
MARGINAL

Default tie-break:
Roll FT
```

---

# 172. Explanations

The UI/LLM should explain optimizer output from structured evidence.

Example:

```text
Transfer B is preferred because:

+2.1 expected points over next 3 GWs
higher expected minutes
better fixtures
same price
no hit required
```

Do not invent qualitative football explanations that are absent from model/context data.

---

# 173. What optimizer must NOT do

Do not:

```text
recommend a transfer because player hauled last week

force use of free transfer

always prefer more expensive player

always bench cheapest player

always captain highest-owned player

always save chips for DGW

always use WC after bad score

ignore selling prices

ignore transfer hits

ignore value of rolling FT
```

---

# 174. Free-first architecture

Optimizer must use only free/open-source software.

Recommended:

```text
SciPy MILP / HiGHS
```

Optional:

```text
OR-Tools
```

No commercial optimization solver is required.

---

# 175. Performance

Normal:

```text
current squad optimization
6GW horizon
reasonable candidate pool
```

should run on a normal developer machine.

Do not introduce cloud optimization infrastructure without need.

---

# 176. Caching

Cache:

```text
player projections
candidate pools
single-GW optimal squads
```

when input hash is unchanged.

---

# 177. Optimizer invalidation

Rerun if:

```text
player projections change
price changes
injury status changes
fixture changes
current squad changes
FT changes
chip state changes
```

---

# 178. Experiment sequence

Recommended implementation order:

## OPT-001

Valid squad MILP.

## OPT-002

Starting XI.

## OPT-003

Captain / vice-captain.

## OPT-004

Bench order.

## OPT-005

Single free transfer.

## OPT-006

Roll FT.

## OPT-007

Multiple FT.

## OPT-008

Hits.

## OPT-009

6GW horizon.

## OPT-010

FT state transition.

## OPT-011

Wildcard.

## OPT-012

Free Hit.

## OPT-013

Bench Boost.

## OPT-014

Triple Captain.

## OPT-015

Chip timing.

## OPT-016

Autosub scenario scoring.

## OPT-017

Sensitivity/confidence.

## OPT-018

Historical optimizer backtesting.

---

# 179. Required unit tests

At minimum:

```text
test_valid_squad_15_players

test_exactly_2_gk
test_exactly_5_def
test_exactly_5_mid
test_exactly_3_fwd

test_max_3_players_per_club

test_budget_constraint

test_starting_xi_11_players

test_one_starting_gk
test_min_3_def
test_min_2_mid
test_min_1_fwd

test_exactly_one_captain
test_exactly_one_vice
test_captain_in_starting_xi
test_vice_in_starting_xi

test_roll_ft_is_valid

test_hit_cost

test_max_5_ft

test_transfer_in_out_balance

test_selling_price_used

test_wildcard_unlimited_transfers

test_free_hit_restores_squad

test_only_one_chip_per_gw

test_bench_boost_counts_bench

test_triple_captain_multiplier

test_deterministic_tie_break
```

---

# 180. FT-specific tests

Examples:

```text
1 FT + roll -> 2 next GW

4 FT + roll -> 5 next GW

5 FT + roll -> still 5

3 FT + use 1 -> correct next-GW state

extra transfer -> -4
```

Exact calculation must follow `fpl_rules.yaml`.

---

# 181. Price tests

Example:

```text
purchase price = 7.5
current price = 7.8
selling price = 7.6
```

Optimizer must receive:

```text
7.6
```

when selling.

---

# 182. Hit test

Scenario:

```text
0 FT

one transfer
```

must incur:

```text
4-point cost
```

if season rules require it.

---

# 183. Autosub test

Starting formation:

```text
3-4-3
```

DEF does not play.

First bench:

```text
MID
```

Second bench:

```text
DEF
```

Optimizer/scoring must select the defender if midfielder substitution would violate minimum DEF count.

---

# 184. Captain fallback test

Captain:

```text
0 minutes
```

Vice:

```text
plays
```

Vice receives captain multiplier.

---

# 185. Both captain and vice DNP

No captain multiplier is applied to another player.

---

# 186. Wildcard tests

Verify:

```text
unlimited transfers
no hit costs
permanent new squad
valid budget
valid positions
club maximum
```

---

# 187. Free Hit tests

Verify:

```text
temporary squad
unlimited transfers
no transfer hit
next-GW squad restored
bank state restored according to rules
```

---

# 188. Bench Boost tests

All eligible squad player points count.

Automatic bench substitution logic becomes irrelevant for point inclusion because bench points are included directly.

---

# 189. Triple Captain tests

Captain total Gameweek points:

```text
×3
```

instead of:

```text
×2
```

Vice inherits TC multiplier if captain does not play according to FPL rules.

---

# 190. Double Gameweek captain test

Captain plays two fixtures:

```text
GW score =
fixture1 + fixture2
```

then captain multiplier applies to the total.

---

# 191. Solver validation

For small synthetic candidate sets:

brute-force enumerate all valid squads.

Compare MILP result.

They must match.

This is an excellent correctness test.

---

# 192. Golden optimizer scenario

Create a small deterministic synthetic FPL universe with:

```text
known prices
known EV
known squad
known FT
```

Manually determine optimal action.

Optimizer must reproduce it.

---

# 193. Historical validation

Run across multiple seasons and squad states.

Compare:

```text
advanced optimizer

vs

no-transfer baseline
greedy GW1
simple 6GW
```

---

# 194. Promotion criteria

Advanced optimizer is promoted only if:

```text
improves historical expected/realized performance
does not generate rule-invalid squads
is reproducible
has acceptable runtime
```

---

# 195. Sensitivity promotion criteria

Confidence layer is useful only if low-confidence recommendations actually correspond to:

```text
smaller margins
greater forecast instability
```

Validate calibration of confidence.

---

# 196. Chip strategy promotion criteria

Chip planner must outperform simple chip heuristics across historical seasons before being trusted automatically.

---

# 197. Current-action priority

The most important optimizer output is:

```text
WHAT SHOULD I DO BEFORE THE NEXT DEADLINE?
```

Future plan explains the current decision but remains provisional.

---

# 198. Final decision hierarchy

Recommended output order:

```text
1. Transfer / roll / chip decision
2. Transfers
3. Starting XI
4. Captain
5. Vice-captain
6. Bench order
7. 3GW / 6GW outlook
8. Alternatives
9. Confidence
```

---

# 199. Acceptance criteria

The Decision Optimizer is accepted when:

1. it creates only valid FPL squads,
2. budget calculations use correct selling prices,
3. club and position constraints are enforced,
4. starting XI formations are valid,
5. captain and vice-captain are valid starters,
6. bench order respects automatic substitution rules,
7. roll FT is always a candidate,
8. up to five stored free transfers are supported,
9. transfer hits are explicitly deducted,
10. multi-transfer combinations are optimized jointly,
11. six-GW planning is supported,
12. future actions are treated as provisional,
13. Wildcard is permanent,
14. Free Hit is temporary,
15. Bench Boost and Triple Captain are supported,
16. chip-period restrictions are configuration-driven,
17. only one chip may be used per Gameweek,
18. no-transfer baseline exists,
19. advanced optimizer is backtested against simpler strategies,
20. projection uncertainty feeds recommendation confidence,
21. marginal recommendations are identified,
22. optimization is reproducible,
23. no commercial solver is required,
24. no LLM participates in mathematical optimization.

---

# 200. Codex implementation guidance

DO:

* implement season rules through `fpl_rules.yaml`,
* create validation constraints first,
* implement simple single-GW MILP first,
* support roll FT explicitly,
* use correct selling prices,
* keep transfer and chip state temporal,
* write brute-force comparison tests,
* implement multi-GW search incrementally,
* retain alternative solutions,
* expose solver metadata,
* keep risk-neutral EV as default objective,
* run sensitivity separately.

DO NOT:

* hardcode 2026/27 rules throughout Python,
* force a transfer,
* ignore the value of rolling,
* greedily choose multi-transfer combinations,
* use current price instead of selling price for owned players,
* optimize only EV/£,
* assume future player prices,
* automatically use chips in DGW/BGW,
* treat future planned transfers as commitments,
* let LLM choose the mathematically optimal squad,
* hide solver failures or optimality gaps.

---

# 201. Final principle

The Decision Optimizer should answer:

```text
GIVEN EVERYTHING WE CURRENTLY BELIEVE
ABOUT PLAYER POINT DISTRIBUTIONS,

THE USER'S EXACT SQUAD STATE,

FPL RULES,

TRANSFER FLEXIBILITY,

CHIPS,

AND THE NEXT SEVERAL GAMEWEEKS,

WHAT ACTION MAXIMIZES EXPECTED FPL VALUE?
```

The system must always be willing to conclude:

```text
THE BEST TRANSFER IS NO TRANSFER.
```

The primary objective remains:

```text
MAXIMIZE OUT-OF-SAMPLE FPL PERFORMANCE

SUBJECT TO REAL FPL CONSTRAINTS

WITHOUT PRETENDING UNCERTAIN DECISIONS ARE CERTAIN.
```

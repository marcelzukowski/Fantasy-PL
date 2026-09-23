# Strict historical policy replay

`python -m fpl_engine.validation.policy_replay --case <frozen-case.json> --mode single --output-dir <directory>`
replays an immutable, typed `DecisionReportV2`. It never runs a policy, downloads data, reads
current FPL state, or mixes realised outcomes into decision inputs.

A strict case requires a verified `PlanningContext`, matching artifact hashes, a prediction and
persisted decision created **strictly before** the official deadline, immutable account/selling-price
state, and later outcome rows with their own source identity and timestamp. The operational selection
rule is: use the **last fully verified pre-deadline analysis/projection context**, never the best
post-outcome run.

Single-decision evaluation applies one saved current action, fixes the resulting 15-player squad, and
compares realised player-point aggregates for 1/3/6 GW with HOLD; transfer hits are deducted separately.
Incomplete outcome coverage is `null`, never zero. Captaincy diagnostics are reported separately.

Sequential replay has a typed carried account and exact historical purchase/selling-price transition
function. It only runs when an executor can make each policy decision against that carried state. The
CLI deliberately reports it unavailable rather than replaying stale decisions after the account diverges.
Missing historical prices are `PRICE_INCOMPLETE`.

Archive before each deadline: PlanningContext, hashed production bundle, DecisionReport, analysis
manifest, canonical market-shadow snapshot, squad/account and prices, and official deadline. Append
later: realised player points, minutes, fixture results and price outcomes. Market shadow remains a
separate frozen artifact, with no policy promotion or weight selection here.

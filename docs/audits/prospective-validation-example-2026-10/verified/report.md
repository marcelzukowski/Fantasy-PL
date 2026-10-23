# Prospective V22 and saved V3 evaluation

Season: 2026/27  
Selected completed gameweeks: 6, 7  

Descriptive frozen-evidence evaluation. Forecast GWs are the sampling unit. Historical V3 results are the saved policy version and were not retroactively replayed with current code. Fewer than 20 GWs do not support uncertainty intervals; no IID player-row intervals are reported.

## V22

### Points forecast

| Cohort | N | MAE | RMSE | Bias (xP - points) |
|---|---:|---:|---:|---:|
| All players | 1334 | 1.0981315592203897 | 2.060364639917602 | -0.1565191904047976 |
| Predicted starters (expected minutes >= 60) | 315 | 2.2843596825396824 | 3.0354698343377757 | -0.23402920634920626 |
| High xP (>= 2) | 382 | 2.2093438481675394 | 2.936150470427811 | -0.23646479057591618 |
| Frozen transfer candidates | 22 | 3.057684090909091 | 4.109347896218948 | -1.0008977272727273 |
| Saved XI candidates | 22 | 3.085731818181818 | 3.823089552758226 | -1.4868045454545453 |

### Minutes forecast

| Cohort | N | MAE | RMSE | Bias (predicted - actual) |
|---|---:|---:|---:|---:|
| All players | 1334 | 14.668777586206897 | 22.199961242653778 | -0.4490602698650674 |

### Position groups

| Position | Points N | Points MAE | Points RMSE | Minutes N | Minutes MAE | Minutes RMSE |
|---|---:|---:|---:|---:|---:|---:|
| GK | 146 | 0.724808904109589 | 1.3497258698591812 | 146 | 8.329293150684931 | 12.493507757516433 |
| DEF | 434 | 1.1953905529953917 | 2.0807543184656287 | 434 | 16.260595276497696 | 23.887630307259847 |
| MID | 596 | 1.130194043624161 | 2.1245454788393867 | 596 | 16.045132466442954 | 23.695272384917285 |
| FWD | 158 | 1.055001582278481 | 2.288950721355596 | 158 | 10.962501265822784 | 18.20682233921506 |

### Predicted-minute buckets

| Bucket | Points N | Points MAE | Minutes N | Minutes MAE |
|---|---:|---:|---:|---:|
| [0,1) | 359 | 0.06406685236768803 | 359 | 0.947075208913649 |
| [1,30) | 462 | 0.7500415584415584 | 462 | 15.87928409090909 |
| [30,60) | 198 | 1.8980555555555556 | 198 | 31.070870707070707 |
| [60,80) | 273 | 2.3409694139194137 | 273 | 19.653519597069597 |
| [80,inf) | 42 | 1.9163964285714286 | 42 | 8.916114285714286 |

## Same-row baselines

Each comparison uses only rows with both a V22 forecast and a complete historical baseline value. Recent-history baselines average up to three available completed gameweeks; each row records the contributing gameweeks and count.

| Cohort | Baseline | Matched N | V22 MAE | Baseline MAE | Baseline RMSE |
|---|---|---:|---:|---:|---:|
| All players | Previous completed GW points | 1334 | 1.0981315592203897 | 1.4032983508245878 | 2.877821931681105 |
| All players | Recent up to three completed GWs | 1334 | 1.0981315592203897 | 1.274862568715642 | 2.3637272255490056 |
| All players | Recent points per minute x predicted minutes | 748 | 1.7563096256684492 | 2.459812337432999 | 3.860805232980488 |
| Predicted starters | Previous completed GW points | 315 | 2.2843596825396824 | 3.2666666666666666 | 4.478874575193802 |
| Predicted starters | Recent up to three completed GWs | 315 | 2.2843596825396824 | 2.767195767195767 | 3.5614534416841606 |
| Predicted starters | Recent points per minute x predicted minutes | 315 | 2.2843596825396824 | 2.603553262406335 | 3.432807132587612 |
| High xP | Previous completed GW points | 382 | 2.2093438481675394 | 3.0706806282722514 | 4.310282360984442 |
| High xP | Recent up to three completed GWs | 382 | 2.2093438481675394 | 2.668411867364747 | 3.4611615572216596 |
| High xP | Recent points per minute x predicted minutes | 382 | 2.2093438481675394 | 2.5057049112448952 | 3.324986972245049 |
| Frozen transfer candidates | Previous completed GW points | 22 | 3.057684090909091 | 3.227272727272727 | 4.395245364957662 |
| Frozen transfer candidates | Recent up to three completed GWs | 22 | 3.057684090909091 | 2.6363636363636362 | 3.2286595398465945 |
| Frozen transfer candidates | Recent points per minute x predicted minutes | 22 | 3.057684090909091 | 2.654215085061781 | 3.430156386524314 |
| Saved XI candidates | Previous completed GW points | 22 | 3.085731818181818 | 4.318181818181818 | 5.596264988202561 |
| Saved XI candidates | Recent up to three completed GWs | 22 | 3.085731818181818 | 3.3181818181818183 | 3.9305845556984207 |
| Saved XI candidates | Recent points per minute x predicted minutes | 22 | 3.085731818181818 | 3.041467903798697 | 3.862429443464172 |

## Per-gameweek metrics

| GW | Point N | Point MAE | Point RMSE | Minutes N | Minutes MAE | Minutes RMSE |
|---:|---:|---:|---:|---:|---:|---:|
| 6 | 667 | 1.1014839580209894 | 2.109956183146371 | 667 | 14.89195532233883 | 22.319585235184526 |
| 7 | 667 | 1.09477916041979 | 2.0095496520484324 | 667 | 14.445599850074963 | 22.079689157232092 |

## Saved V3 versus frozen HOLD

Same-context, no-chip current-GW counterfactuals use saved XI/bench order, observed outcomes, the canonical exact autosub evaluator, captain/vice fallback and frozen hits. No lineup is selected with hindsight. Terminal FT value and future planned actions are not realised points here; these scores do not establish current-policy superiority.

| GW | V3 points | HOLD points | V3 - HOLD |
|---:|---:|---:|---:|
| 6 | 51.0 | 41.0 | 10.0 |
| 7 | 81.0 | 83.0 | -2.0 |

Paired GWs: 2; mean V3 - HOLD: 4.0; total gain: 8.0.

Baselines are matched to the same player-GW rows. Missing history values are excluded rather than imputed.

## Selection and exclusions

Primary archives: 2; exclusions: 2.

## Decision evidence

GW6 saved_v3: SCORED — 51.0
GW6 saved_v3_hold: SCORED — 41.0
GW7 saved_v3: SCORED — 81.0
GW7 saved_v3_hold: SCORED — 83.0

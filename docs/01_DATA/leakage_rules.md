# Data Leakage Rules

## Fundamental rule

For every historical prediction:

feature_timestamp < prediction_timestamp

Prediction timestamp must be before the target FPL deadline.

## Point-in-time principle

The model may only access information that was actually available at prediction time.
Future knowledge must never influence historical features.

## Examples of forbidden leakage

The following are forbidden when predicting a historical GW:

- match statistics from the target fixture,
- player injuries announced after prediction timestamp,
- future player prices,
- future ownership,
- closing bookmaker odds published after prediction timestamp,
- final season aggregates,
- season totals calculated using future matches,
- future lineups,
- future formations,
- future manager changes,
- future transfers,
- corrected post-match data not available at prediction time,
- FPL xP unless a valid pre-deadline snapshot exists.

## Rolling statistics

Rolling features must be calculated only from matches completed before prediction_timestamp.

Example:

When predicting GW10:

allowed:
GW1-GW9

forbidden:
GW10+

## Season aggregates

Never use a final season aggregate when predicting an earlier GW.

Instead calculate:

season_to_date(feature, prediction_timestamp)

## Injury/news data

Historical injury and availability data must come from a point-in-time snapshot whenever possible.

The preferred historical snapshot rule is:

latest_snapshot_timestamp < FPL_deadline

## Bookmaker data

Only odds known before prediction_timestamp are allowed.

Closing odds are forbidden if they were produced after the relevant FPL deadline.

## Tests

The data pipeline must contain automated leakage tests.

A generated feature dataset should contain:

feature_timestamp
prediction_timestamp
target_fixture_id
target_gameweek

Required invariant:

feature_timestamp <= prediction_timestamp

No row violating this condition may reach training or backtesting.

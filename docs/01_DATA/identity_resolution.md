# Identity Resolution Specification

## Purpose

The FPL Prediction & Decision Engine consumes data from multiple providers.

The same real-world entity may have different identifiers, names and metadata across:

- Official FPL API,
- vaastav historical datasets,
- fplcache,
- football-data.co.uk,
- advanced football data provider,
- bookmaker data,
- manual context files.

The system must never rely on provider-specific identifiers as canonical identifiers.

Identity resolution is a first-class data problem.

The objective is to create stable internal identities for:

- players,
- teams,
- fixtures,
- competitions,
- managers,

and map all provider records to those identities in a reproducible, auditable and time-aware way.

---

# 1. Fundamental principle

Every real-world entity receives exactly one internal canonical ID.

Examples:

```text
player_id = ply_01JXYZ...
team_id = team_01JXYZ...
fixture_id = fix_01JXYZ...
manager_id = mgr_01JXYZ...
competition_id = comp_01JXYZ...
```

Provider IDs are treated only as external references.

Never use:

```text
fpl_player_id
sportmonks_player_id
provider_team_id
```

as the primary key of the analytical system.

---

# 2. Canonical entity IDs

Internal IDs must be:

- stable,
- provider-independent,
- immutable,
- unique,
- never recycled.

Recommended implementation:

UUIDv7 or ULID.

Preferred naming:

```text
player_id
team_id
fixture_id
manager_id
competition_id
```

Human-readable names are never primary keys.

---

# 3. Canonical player registry

Create a canonical table:

```text
dim_player
```

Required fields:

```text
player_id
canonical_name
first_name
last_name
known_as
date_of_birth
nationality
preferred_foot
created_at
updated_at
identity_status
```

`identity_status` allowed values:

```text
confirmed
auto_matched
manual_review
unresolved
retired
```

Optional metadata may be added later.

---

# 4. Provider player mapping

Create:

```text
map_player_provider
```

Required fields:

```text
player_id
provider
provider_player_id
provider_player_name
effective_from
effective_to
match_method
match_confidence
review_status
created_at
updated_at
```

Primary uniqueness rule:

```text
(provider, provider_player_id, effective_from)
```

A provider identifier must map to exactly one canonical player within a valid effective period.

---

# 5. Player mapping methods

Allowed `match_method` values:

```text
exact_external_id
exact_name_dob
normalized_name_dob
name_team_dob
name_team
fuzzy_name_dob
fuzzy_name_team
cross_provider_bridge
manual_override
```

Preferred priority:

1. trusted external ID bridge,
2. exact name + date of birth,
3. normalized name + date of birth,
4. name + team + date of birth,
5. name + team,
6. fuzzy match with strong secondary evidence,
7. manual resolution.

Never accept fuzzy name matching alone for automatic confirmation.

---

# 6. Name normalization

Names must be normalized before matching.

Create a deterministic function:

```python
normalize_person_name(name: str) -> str
```

Normalization should include:

- Unicode normalization,
- lowercase,
- trim whitespace,
- collapse repeated whitespace,
- normalize punctuation,
- normalize hyphens/apostrophes,
- remove non-semantic dots,
- optional accent-insensitive comparison.

Examples:

```text
"João Pedro" -> "joao pedro"
"Joao Pedro" -> "joao pedro"
"M. Ødegaard" -> "m odegaard"
"Martin Ødegaard" -> "martin odegaard"
```

Important:

The normalized value is only used for matching.

The canonical display name must preserve proper spelling.

---

# 7. Aliases

Create:

```text
player_alias
```

Fields:

```text
player_id
alias
normalized_alias
source
effective_from
effective_to
confidence
```

Examples of aliases:

- full legal name,
- shortened football name,
- transliterated name,
- provider-specific abbreviation,
- previous surname,
- accented/unaccented version.

Aliases must never create a second player automatically if the date of birth and other evidence indicate the same person.

---

# 8. Date of birth

Date of birth is one of the strongest identity signals.

Matching rules:

```text
same normalized name + same DOB
```

may be auto-confirmed at high confidence.

If names are similar but DOB differs:

```text
DO NOT AUTO-MATCH.
```

If DOB is unavailable:

use additional evidence such as:

- team,
- nationality,
- position,
- transfer history,
- competition history.

---

# 9. Team identity

Create:

```text
dim_team
```

Fields:

```text
team_id
canonical_name
short_name
country
city
created_at
updated_at
```

Provider mapping:

```text
map_team_provider
```

Fields:

```text
team_id
provider
provider_team_id
provider_team_name
effective_from
effective_to
match_method
match_confidence
review_status
```

---

# 10. Team name normalization

Team names vary between providers.

Example:

```text
Manchester United
Man United
Man Utd
Manchester Utd
```

All must resolve to the same:

```text
team_id
```

Create:

```text
team_alias
```

Fields:

```text
team_id
alias
normalized_alias
source
effective_from
effective_to
```

Do not use string equality alone.

---

# 11. Player-team spells

A player identity is independent of club membership.

A transfer must never create a new `player_id`.

Create:

```text
fact_player_team_spell
```

Fields:

```text
player_id
team_id
competition_id
effective_from
effective_to
transfer_type
source
source_record_id
retrieved_at
confidence
```

Examples:

```text
Player X
Club A
2024-07-01 -> 2026-06-30

Player X
Club B
2026-07-01 -> null
```

This enables historical statistics from the previous club to remain attached to the same player.

---

# 12. Transfers

When a player moves clubs:

```text
player_id remains unchanged.
team_id changes through player_team_spell.
```

The transfer should also generate context for the regime-change engine.

Derived fields may include:

```text
club_change_flag
days_since_club_change
previous_team_id
current_team_id
previous_competition_id
current_competition_id
league_change_flag
```

---

# 13. Cross-league players

Players arriving from another league must preserve the same canonical player identity.

Example:

```text
advanced provider:
player_id_external = 123456
league = Ligue 1

later:

FPL API:
fpl_player_id = 777
team = Premier League club
```

These records must resolve to the same internal:

```text
player_id
```

Preferred evidence:

1. provider bridge ID,
2. exact DOB,
3. normalized full name,
4. nationality,
5. transfer destination,
6. transfer date,
7. historical club.

Cross-league history is critical for player talent modelling.

---

# 14. Historical FPL IDs

FPL IDs must not be assumed stable across seasons.

Therefore:

```text
fpl_player_id
```

must always be associated with:

```text
season
```

Recommended mapping key:

```text
(provider="fpl", season, provider_player_id)
```

Never assume:

```text
FPL ID 123 in 2025/26 == FPL ID 123 in 2026/27.
```

Resolution must happen through canonical identity.

---

# 15. Vaastav mapping

Vaastav usually reflects FPL identities from a given season.

Treat Vaastav player identifiers as:

```text
provider = vaastav
season = YYYY-YY
provider_player_id
```

Where possible, bridge:

```text
vaastav season player
        ↓
same-season FPL player
        ↓
canonical player_id
```

Prefer ID bridges over name matching.

---

# 16. fplcache mapping

fplcache snapshots represent official FPL state.

Mapping should be:

```text
fplcache provider_player_id
    ↓
FPL season/player ID
    ↓
canonical player_id
```

Do not create independent player identities from fplcache names.

---

# 17. Fixture identity

Fixture identity must also be provider-independent.

Create:

```text
dim_fixture
```

Fields:

```text
fixture_id
competition_id
season
home_team_id
away_team_id
scheduled_kickoff
status
created_at
updated_at
```

Provider mapping:

```text
map_fixture_provider
```

Fields:

```text
fixture_id
provider
provider_fixture_id
provider_kickoff
match_confidence
match_method
```

---

# 18. Fixture matching

Preferred fixture matching order:

1. trusted provider fixture bridge,
2. competition + season + home_team + away_team + kickoff proximity,
3. home_team + away_team + date,
4. manual resolution.

Kickoff timestamps may change.

Therefore do not require exact timestamp equality.

Recommended tolerance for automatic fixture matching:

```text
same teams
AND
kickoff difference <= 48 hours
```

when identifying postponed/rescheduled fixtures.

After fixture identity is established, changing kickoff time must update the fixture, not create a new fixture.

---

# 19. Postponed and rescheduled fixtures

A postponed match retains the same:

```text
fixture_id
```

if it is clearly the same scheduled competition fixture.

Only:

```text
scheduled_kickoff
gameweek_assignment
status
```

change over time.

Historical point-in-time snapshots must preserve what was known at each prediction timestamp.

---

# 20. Double Gameweeks and Blank Gameweeks

Gameweek is not part of fixture identity.

A fixture may move from:

```text
GW X
```

to:

```text
GW Y
```

without becoming a new fixture.

Store FPL GW assignment as time-aware fixture metadata.

This is essential for:

- DGW,
- BGW,
- postponements,
- rescheduling.

---

# 21. Competition identity

Create:

```text
dim_competition
```

Examples:

```text
Premier League
Champions League
Europa League
Conference League
FA Cup
EFL Cup
Bundesliga
La Liga
Ligue 1
Serie A
```

Fields:

```text
competition_id
canonical_name
country
competition_type
tier
```

Provider mapping:

```text
map_competition_provider
```

is required.

Competition identity is important for:

- fixture congestion,
- cross-league player history,
- league strength adjustment.

---

# 22. Manager identity

Create:

```text
dim_manager
```

and:

```text
map_manager_provider
```

A manager change must be represented through:

```text
fact_manager_team_spell
```

Fields:

```text
manager_id
team_id
effective_from
effective_to
source
confidence
```

A new manager must not create a new `team_id`.

---

# 23. Manager-team temporal logic

When determining a team's manager for a historical fixture:

use:

```text
fixture_time BETWEEN effective_from AND effective_to
```

When predicting historically:

the manager change may only be used if it was known before:

```text
prediction_timestamp
```

If a manager appointment was announced after the FPL deadline:

it must not influence that historical prediction.

---

# 24. Temporal identity mappings

Mappings may change over time.

Therefore mappings must support:

```text
effective_from
effective_to
```

This is particularly important for:

- player-team spells,
- provider corrections,
- team renaming,
- competition restructuring,
- provider ID reuse.

Never silently overwrite historical mappings.

---

# 25. Matching confidence

Every non-exact identity resolution should contain:

```text
match_confidence
```

Range:

```text
0.0 – 1.0
```

Suggested thresholds:

```text
>= 0.98
auto_confirm

0.90 – 0.979999
auto_match_but_flag_for_review

0.75 – 0.899999
manual_review_required

< 0.75
unresolved
```

Thresholds are initial defaults and may later be adjusted.

---

# 26. Automatic matching score

A candidate scoring system may use:

```text
DOB exact                  +0.40
normalized full name exact +0.30
team exact                 +0.10
nationality exact          +0.05
position compatible        +0.05
transfer evidence          +0.10
```

This is only a starting rule-based resolver.

Do not treat these exact weights as permanent modelling truth.

They may be tuned after evaluating matching errors.

---

# 27. Fuzzy matching

Fuzzy matching may be used only to generate candidates.

It must not be the sole basis for automatic identity confirmation.

Recommended process:

```text
candidate generation
    ↓
secondary evidence
    ↓
confidence score
    ↓
auto-confirm or manual review
```

Candidate generation may use:

- Levenshtein distance,
- token sort ratio,
- Jaro-Winkler,
- normalized aliases.

---

# 28. Same-name players

If two players share the same or nearly identical name:

name-based resolution is insufficient.

Require additional evidence:

- DOB,
- team,
- nationality,
- historical club,
- provider bridge.

The pipeline must fail safely rather than choose arbitrarily.

---

# 29. Position mismatch

Position differences between providers do not necessarily indicate different identities.

Example:

```text
FPL: MID
advanced provider: RW
another provider: AM
```

These may still be the same player.

Position should be treated as supporting evidence, not a hard identity key.

---

# 30. Manual overrides

Create:

```text
config/identity/manual_player_mappings.yaml
```

Example:

```yaml
mappings:

  - provider: advanced_provider
    provider_player_id: "123456"
    canonical_player_id: "ply_..."
    reason: "Verified transfer + DOB + full name"
    effective_from: "2026-07-01"
    effective_to: null
```

Manual overrides must always record:

```text
reason
author
created_at
```

Optional:

```text
source_url
notes
```

Manual overrides have highest priority.

---

# 31. Manual unresolved queue

Create a review artifact:

```text
data/interim/identity_review_queue.parquet
```

Suggested columns:

```text
entity_type
provider
provider_id
provider_name
candidate_canonical_id
candidate_name
match_confidence
match_method
reason_for_review
created_at
```

This allows unresolved records to be reviewed without blocking unrelated ingestion.

---

# 32. No silent new identities

The system must not automatically create a new canonical player merely because a provider record cannot be matched.

Process:

```text
unmatched record
    ↓
candidate search
    ↓
confidence check
    ↓
manual review if needed
    ↓
only then canonical entity creation
```

Exception:

a genuinely new player can be created when strong evidence shows no existing canonical identity.

---

# 33. Identity provenance

Every mapping must retain provenance.

Required:

```text
provider
provider_record_id
retrieved_at
matching_method
confidence
mapping_created_at
mapping_updated_at
```

This is essential for debugging historical data.

---

# 34. Identity versioning

Identity mappings are data, not code.

Changes must be versionable.

Recommended:

```text
data/identity/
```

with:

```text
players.parquet
teams.parquet
fixtures.parquet
competitions.parquet
managers.parquet

player_provider_map.parquet
team_provider_map.parquet
fixture_provider_map.parquet
competition_provider_map.parquet
manager_provider_map.parquet
```

For development and review, YAML/CSV may be used for manual overrides.

Parquet should be preferred for generated canonical registries.

---

# 35. Database representation

When DuckDB is introduced, recommended logical tables:

```sql
dim_player
dim_team
dim_fixture
dim_competition
dim_manager

map_player_provider
map_team_provider
map_fixture_provider
map_competition_provider
map_manager_provider

fact_player_team_spell
fact_manager_team_spell

player_alias
team_alias
```

---

# 36. Data ingestion flow

Recommended identity-resolution flow:

```text
RAW PROVIDER DATA
        ↓
NORMALIZE PROVIDER RECORD
        ↓
LOOK FOR EXACT PROVIDER MAPPING
        │
        ├── found → canonical ID
        │
        └── not found
                ↓
        GENERATE CANDIDATES
                ↓
        SCORE CANDIDATES
                ↓
        ┌──────────────────────────────┐
        │ >= auto threshold           │
        │ map automatically           │
        └──────────────────────────────┘
                │
                ├── ambiguous → review queue
                │
                └── genuinely new → create canonical entity
```

---

# 37. Player identity resolution algorithm

Initial algorithm:

```text
1. Check manual override.
2. Check exact provider ID mapping.
3. Check trusted provider bridge.
4. Normalize name.
5. Search candidates by DOB.
6. Search candidates by normalized name.
7. Add current/historical team evidence.
8. Add nationality evidence.
9. Add transfer evidence.
10. Calculate confidence.
11. Resolve or send to review queue.
```

---

# 38. Team identity resolution algorithm

Initial algorithm:

```text
1. Check manual override.
2. Check exact provider mapping.
3. Normalize club name.
4. Compare aliases.
5. Compare competition/country.
6. Calculate confidence.
7. Resolve or review.
```

---

# 39. Fixture identity resolution algorithm

Initial algorithm:

```text
1. Check provider fixture map.
2. Resolve canonical home team.
3. Resolve canonical away team.
4. Resolve competition.
5. Search candidate fixtures for same teams and season.
6. Compare kickoff timestamps.
7. Handle rescheduled/postponed case.
8. Resolve or review.
```

---

# 40. Historical correctness

Identity resolution must never create historical leakage.

Example:

A transfer occurring on August 20 cannot cause the player to be assigned to the new club for a historical prediction made August 10.

All club and manager relationships must be resolved using:

```text
effective_from <= prediction_timestamp
```

and, where relevant:

```text
effective_to > prediction_timestamp
```

---

# 41. Raw data preservation

Never modify raw provider records to replace IDs.

Raw records remain unchanged.

Canonical IDs are added only in:

```text
interim
processed
feature
```

layers.

This preserves reproducibility.

---

# 42. Identity resolution output contract

Every normalized record that refers to a player should ultimately contain:

```text
player_id
source_provider
source_player_id
identity_match_method
identity_match_confidence
```

Every fixture should contain:

```text
fixture_id
home_team_id
away_team_id
competition_id
```

---

# 43. Failure policy

Identity ambiguity is not a warning-only issue.

For data used in training or prediction:

```text
unresolved critical identity
```

must either:

1. be excluded explicitly,
2. be resolved manually,
3. fail the relevant pipeline stage.

Never silently attach uncertain statistics to the most similar player.

---

# 44. Automated tests

The project must contain tests for identity resolution.

Minimum tests:

## Player tests

```text
same provider ID resolves deterministically
same name + DOB resolves correctly
accented/unaccented aliases resolve correctly
same name + different DOB does not resolve automatically
club transfer preserves player_id
FPL ID change between seasons preserves player_id
cross-league transfer preserves player_id
ambiguous fuzzy match enters review queue
manual override wins over automated matching
```

## Team tests

```text
Man Utd == Manchester United
team rename preserves team_id
different clubs with similar names are not merged
```

## Fixture tests

```text
same fixture across providers resolves to one fixture_id
kickoff reschedule preserves fixture_id
postponed match preserves fixture_id
reverse fixture does not match
same teams in different competitions do not match
```

## Temporal tests

```text
future club spell is not active before effective_from
future manager spell is not active before announcement/effective time
provider mapping history is not overwritten
```

---

# 45. Data quality invariants

Required invariants:

```text
one active provider player ID -> max one canonical player
one active provider team ID -> max one canonical team
one provider fixture ID -> exactly one canonical fixture
player_team_spell intervals must not overlap for the same competition context unless explicitly allowed
manager_team_spell intervals must not conflict
canonical IDs never change after creation
manual mappings must reference existing canonical IDs
```

---

# 46. Monitoring

Generate an identity-resolution report after ingestion.

Example:

```text
Players processed: 1,240
Exact mapped: 1,173
Auto matched: 42
Manual mappings: 18
Review required: 5
Unresolved: 2

Average confidence: 0.992
```

The report should list all ambiguous mappings.

---

# 47. Metrics

Track:

```text
auto_match_rate
manual_review_rate
unresolved_rate
incorrect_match_rate
duplicate_identity_rate
mapping_confidence_distribution
```

The most important metric is:

```text
incorrect_match_rate
```

False merges are more dangerous than temporarily unresolved players.

Therefore prefer conservative matching.

---

# 48. Acceptance criteria

Identity resolution is considered production-ready when:

1. every current Premier League FPL player has a canonical `player_id`,
2. every current Premier League club has a canonical `team_id`,
3. historical FPL season IDs resolve across seasons,
4. cross-league transferred players preserve historical identity,
5. all current fixtures map deterministically,
6. ambiguous records enter a review queue,
7. no fuzzy-name-only auto matching is possible,
8. temporal mappings pass all tests,
9. raw data remains immutable,
10. provider mappings are reproducible.

---

# 49. Codex implementation guidance

When implementing this specification:

DO:

- use small deterministic functions,
- separate normalization from matching,
- separate candidate generation from final resolution,
- preserve source metadata,
- write tests first for ambiguous cases,
- keep manual overrides outside code,
- make thresholds configurable.

DO NOT:

- hardcode player IDs in Python source,
- use names as database primary keys,
- silently create duplicate players,
- merge players based only on fuzzy names,
- mutate raw provider data,
- assume FPL IDs are stable across seasons,
- assume kickoff times never change.

---

# 50. Initial suggested files

When implementation begins, expected structure:

```text
src/fpl_engine/identity/
    __init__.py
    models.py
    normalization.py
    player_resolver.py
    team_resolver.py
    fixture_resolver.py
    manager_resolver.py
    candidate_scoring.py
    registry.py
    review_queue.py

config/identity/
    matching_thresholds.yaml
    manual_player_mappings.yaml
    manual_team_mappings.yaml
    manual_fixture_mappings.yaml

tests/identity/
    test_name_normalization.py
    test_player_resolution.py
    test_team_resolution.py
    test_fixture_resolution.py
    test_temporal_mappings.py
```

This structure is a recommendation, not a hard requirement.

Codex may propose a simpler structure if it preserves all architectural guarantees.

---

# 51. Final principle

Identity resolution should optimize for:

```text
CORRECTNESS > COVERAGE > AUTOMATION
```

A temporarily unresolved player is acceptable.

A confidently wrong player mapping is not.

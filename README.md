# FPL Prediction & Decision Engine

## Overview

This repository contains an end-to-end Fantasy Premier League prediction and decision system.

The system is designed to:

```text
predict football events
↓
simulate fixture outcomes
↓
calculate FPL point distributions
↓
optimize FPL decisions
```

The project does NOT primarily predict total FPL points directly.

Instead, it models the underlying football processes that generate those points.

---

# Development setup

Requires Python 3.11 or newer. The distribution is named
`fpl-prediction-engine`; the import package is `fpl_engine` under `src/`.
Hatchling builds the package.

From the repository root, using uv and PowerShell:

```powershell
uv venv --python 3.11
uv pip install --editable . --group dev
.venv/Scripts/python.exe -m pytest -q
```

On macOS/Linux, use `.venv/bin/python` for the test command.
The existing `pytest.ini` configures test discovery and source imports.

The default installation includes the core and modelling dependencies from
CORE-002. The `dev` dependency group adds `pytest` and `pytest-cov`.
To also install optional Optuna support:

```powershell
uv pip install --editable ".[optuna]" --group dev
```

These commands do not create a lock file. Package initializers currently contain
no business logic.

Configuration loading (CORE-003):

```python
from fpl_engine.config.loader import load_scoring_rules_config

config = load_scoring_rules_config()
print(config.season, config.goals["forward"])
```

Canonical loaders locate `docs/` relative to the source checkout, independently
of the working directory. For a wheel installation, supply
`project_root=Path("/path/to/checkout")`; the wheel does not bundle these documents.
`load_yaml_config(Path("config.yaml"))` accepts a mapping with an integer `version`;
pass `model=ScoringRulesConfig` (or another subclass) for a stricter contract.
`config.model_dump()` exposes all fields, including nested sections. Each load
returns independent data. Failures raise `ConfigError` subclasses with the path.

Project logging (CORE-004):

```python
from fpl_engine.logging import bind_context, configure_logging, get_logger

configure_logging()  # INFO to stderr; pass level="DEBUG" or stream=... as needed.
logger = bind_context(get_logger(__name__), target_gameweek=5)
logger.info("Configuration ready")
```

Output contains a UTC timestamp, level, logger name, message and sorted structured
context. Rebinding copies context; newer values win, with per-call `extra` taking
precedence. Standard LogRecord field names are reserved. Do not put credentials
in context. Normal `logger.exception(...)` includes the traceback.
Configuration reuses one owned handler on `fpl_engine` and disables propagation
from it to the root; it preserves caller-installed handlers. Import alone does
not configure logging. Use child loggers without extra handlers for single output.

Canonical metadata (CORE-005):

```python
from datetime import datetime, timezone
from fpl_engine.types import PredictionContext

context = PredictionContext(
    prediction_timestamp=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
    target_gameweek=5,
    target_season="2026/27",
)
```

`PredictionContext`, `DatasetVersion`, `FeatureVersion`, `ModelVersion` and
`SourceProvenance` are frozen Pydantic models. Pass aware datetime objects;
timestamps normalize to UTC. Identifiers are non-empty strings with surrounding
whitespace removed; other types and unknown fields are rejected. Use
`model_dump()` / `model_dump_json()` for serialization and `model_validate_json()`
to read serialized timestamps. Required timestamps have no automatic defaults.
Provenance keeps effective time, known time and retrieval time separate; optional
times remain `None` when absent. These types do not perform leakage checks.

Raw storage (DATA-001):

```python
from datetime import datetime, timezone
from pathlib import Path
from fpl_engine.data.raw_store import RawStore

store = RawStore(Path("data/raw"))
snapshot = store.store_json(
    {"items": [{"id": 1}]},
    source_provider="example_provider",
    entity="items",
    retrieved_at=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
)
content = store.read_bytes(snapshot)  # Verifies sidecar, length and SHA-256.
```

`store_bytes()` preserves bytes exactly; explicitly encode text as UTF-8 if
needed (no newline conversion is performed). Both writes accept optional
`source_url` and `source_record_id`. JSON uses sorted keys, compact separators
and UTF-8; unsupported values, non-string keys and non-finite numbers fail.
The frozen `RawSnapshot` extends `SourceProvenance`; `source_provider` exposes
its canonical `source`. Sidecars serialize that field as `source_provider`.

Layout: `{root}/{provider}/{entity}/{UTC-date}/{snapshot_id}/payload.json`
(or `payload.bin`) plus `snapshot.metadata.json`. Paths in metadata are relative
to the root. Snapshot IDs hash provider, entity, UTC retrieval time, payload
format, SHA-256 of the exact stored bytes, and validated `source_record_id` and
`source_url` strings (absent values become JSON null). Identity uses sorted,
compact UTF-8 JSON; URLs are not canonicalized or placed in filenames. Payload
checksums depend only on payload bytes. Repeating the exact same snapshot raises
`RawSnapshotExistsError` and preserves existing evidence.
New IDs use the corrected source-aware algorithm; existing snapshots are not
rewritten and remain readable through their receipts. Re-storing a legacy
snapshot may create a new ID. `metadata_version=1` remains unchanged because it
versions the metadata schema, not the identity algorithm.

Publication reserves the snapshot directory exclusively, fsyncs temporary files
and publishes them using no-overwrite hard links, metadata last. This requires
filesystem hard-link support (tested on Windows/NTFS); unsupported filesystems
fail explicitly. A crash can leave an incomplete directory: reads reject it and
writes do not replace it. This is not a two-file transaction or a guarantee of
directory-entry durability after power loss. Normal write failures attempt to
remove only their own incomplete files.
Provider/entity names use 1–64 ASCII letters, digits, underscores or hyphens
(the first character cannot be a hyphen); Windows device names are rejected.
Resolved paths must remain inside the root. Hostile concurrent replacement of
filesystem links is outside this local storage layer's guarantees.

HTTP cache (DATA-002):

```python
from datetime import timedelta
from pathlib import Path
from fpl_engine.data.http_cache import CacheRequest, HttpCache, HttpResponse

cache = HttpCache(Path("data/interim/http_cache"))
request = CacheRequest(
    namespace="example_provider", method="GET", url="https://example.test/items",
    params={"page": 1}, vary={"account_scope": "public"},
)
result = cache.get_or_fetch(
    request,
    fetcher=lambda: HttpResponse(status_code=200, body=b'{ "items": [] }'),
    ttl=timedelta(minutes=5),
)
print(result.from_cache)  # False on fetch; True on a subsequent fresh hit.
cache.invalidate(request)
```

The example uses a fake fetcher; callers supply their own transport. `put(request,
response, ttl=...)` supports direct writes. `get(request)` returns `CacheLookup`
with `MISS`, `HIT_FRESH` or `HIT_STALE` and an optional `CachedHttpResponse`.
Returned responses and their copied headers are immutable. Pass `clock=...` to
inject an aware datetime clock; stored times normalize to UTC.

Policy is explicit: `ttl=None` never expires automatically; a non-negative
`timedelta` expires at `stored_at + ttl`. Fresh means `now < expires_at`; zero is
immediately stale. Reads never extend TTL. A policy passed on a later lookup
applies only if a new response is fetched. `get_or_fetch()` refreshes stale
entries and propagates errors without stale fallback or retries. Only 2xx
responses are persisted. Other statuses return `from_cache=False` and leave any
old entry unchanged. Cache-Control is retained as metadata, not interpreted;
the caller decides whether caching is appropriate.

Keys are SHA-256 over versioned deterministic UTF-8 identity: namespace,
uppercased method, URL, query, tagged body digest and `vary`. Query names sort
stably, retaining repeated-value order. Params accept string/integer values in
a mapping or a sequence of pairs; URL queries use UTF-8 form decoding (including
`+` as space and bare flags as empty values). Authority/path spelling is retained;
userinfo, fragments, controls and malformed percent escapes are rejected.
Bodies support None, bytes, text and JSON values with sorted object keys; these
representations have distinct tags. Caller objects are not mutated.

Use `sensitive_params=("api_key", "token")` consistently for secret query names
in both the URL and params. Names are case-sensitive and not auto-detected.
Secret values affect the hash but are replaced by `[REDACTED]` in the persisted
URL. `CacheRequest` retains only that redacted description and the fingerprint;
keep the original inputs separately for transport. Request bodies and `vary`
are not persisted. Request headers are not accepted; use non-secret account or
header discriminators in `vary` and non-secret namespace names. Response headers
are restricted to lowercase Content-Type, ETag, Last-Modified and Cache-Control;
Authorization, API-key, Cookie and Set-Cookie headers are dropped. No cache
logging is performed. Response **body bytes remain exact**, including any data
the provider puts in them.

Layout: `{root}/{namespace}/{key[:2]}/{key}.zip`. Each standard, uncompressed ZIP
contains `response.bin` and `cache.metadata.json`; this single-file layout allows
atomic refresh. Metadata records version, key, namespace, request method,
redacted URL, fingerprint, status, safe headers, UTC stored/expiry times, SHA-256
body checksum, algorithm, byte length and `payload_path="response.bin"` relative
to the archive. ZIP member timestamps are fixed; operational timestamps come
only from the clock. Lookup validates the container, metadata, request identity,
body length and checksum; corruption raises `HttpCacheIntegrityError`. Checks
detect corruption, not cryptographic authenticity. Archives are never extracted.

Publication fsyncs and closes a temporary ZIP in the destination directory,
then uses `os.replace()`. Readers see a complete old or new entry. A short
process-local lock coordinates filesystem operations across cache instances;
fetchers run outside it, so simultaneous misses may both fetch. Cross-process
Windows sharing violations may raise `HttpCacheWriteError`, preserving the old
entry. Filesystems must support atomic same-filesystem replacement; power-loss
directory durability is not guaranteed. Failed writes clean up their own temp
file when possible. Namespace/path safety follows the portable restrictions
described for RawStore, including resolved-root checks and the same limitation
on hostile concurrent link replacement.

`invalidate(request)` removes only that request's ZIP and returns whether it
existed. A concurrent in-flight fetch may subsequently repopulate it. Empty
directories are retained; there is no global cleanup. This operational cache is
separate from immutable RawStore evidence and does not create historical snapshots.

Official FPL adapter (DATA-003):

```python
from datetime import timedelta
from pathlib import Path
import httpx
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter

with httpx.Client() as client:
    adapter = OfficialFPLAdapter(
        client=client,
        cache=HttpCache(Path("data/interim/http_cache")),
        raw_store=RawStore(Path("data/raw")),
        ttl=timedelta(minutes=5),  # Example caller policy, not an endpoint default.
        timeout=10.0,
    )
    result = adapter.get_bootstrap_static()
    players = result.payload["elements"]  # Official FPL fields and provider IDs.
    print(result.from_cache)
```

The caller owns the synchronous `httpx.Client` and its lifetime. Use a dedicated
public client without authentication, cookies or default query parameters that
could change request identity. The adapter does not configure credentials or
logging. `timeout` is finite positive seconds for HTTPX request phases; redirects
and adapter retries are disabled. All normal tests use `httpx.MockTransport`.
`base_url` defaults to `https://fantasy.premierleague.com/api/` and can be injected
without query parameters, fragments or userinfo.

Methods: `get_bootstrap_static()`, `get_fixtures(event=None)`,
`get_element_summary(player_id)` and `get_event_live(gameweek)`. Fixtures without
an event use one all-fixtures request. IDs must be strictly positive integers;
GWs must be integers in 1..38. Strings and booleans are rejected. FPL IDs remain
provider identifiers. Root objects require the documented endpoint keys;
fixtures require a list. Extra fields and nested provider values are retained.

TTL is mandatory constructor policy (`None` for immutable or a non-negative
`timedelta`). Requests use cache namespace `official_fpl_api`. Fresh hits return
cached bytes without HTTP or new raw evidence. A miss/stale refresh performs
HTTP, rejects non-2xx, stores exact `httpx.Response.content` bytes in RawStore,
updates HttpCache, then parses JSON and validates the endpoint root. These are
the body bytes delivered by HTTPX, after any transport decompression. Successful
HTTP bodies with invalid JSON/shape remain in raw storage and the HTTP cache;
adapter reads still raise errors, including on cache hits, until refresh or
explicit cache invalidation.

`FPLApiResult` contains a fresh mutable `payload`, immutable cached `response`,
`from_cache`, and `raw_snapshot` only for an actual fetch in that call. Raw
metadata records `official_fpl_api`, endpoint entity, source URL (including GW
filter), provider record ID where applicable and aware UTC `retrieved_at`.
Pass `clock=...` for deterministic retrieval times, and inject the same clock
into HttpCache when desired. Cache `stored_at` is a separate operational write
time; a hit does not invent historical retrieval/publication metadata.

Errors derive from `FPLApiError`: `FPLApiValidationError`, `FPLApiRequestError`,
`FPLApiResponseError` (including `FPLApiParseError`) and `FPLApiStorageError`.
Transport/storage/parse causes are chained; adapter messages include endpoint
context without response bodies. Raw-write failure prevents cache publication;
cache-write failure leaves existing raw evidence available for audit.

RawStore identity includes source URL and provider record ID, so different
players, GWs or fixture query variants can store identical bytes at the same
retrieval timestamp. Exact duplicates still raise `FPLApiStorageError` chained
from `RawSnapshotExistsError`; the adapter never fabricates a new timestamp.
The filesystem limitations of RawStore and HttpCache described above still apply.

Vaastav historical FPL adapter (DATA-004):

```python
from datetime import timedelta
from pathlib import Path
import httpx
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.providers.vaastav import VaastavAdapter

with httpx.Client() as client:
    vaastav = VaastavAdapter(
        client=client,
        cache=HttpCache(Path("data/interim/http_cache")),
        raw_store=RawStore(Path("data/raw")),
        repository_ref="0123456789abcdef0123456789abcdef01234567",
        ttl=None,
    )
    dataset = vaastav.get_merged_gameweeks("2024-25")
    rows = dataset.data
```

`repository_ref` is required and appears in the URL, returned receipt and raw
provenance. Use a commit SHA for reproducible historical backtests. Tags and
branches, including `master`, are accepted as caller-supplied mutable refs; the
adapter does not resolve them through GitHub or Git and never represents them as
immutable source versions. Pick an explicit finite TTL for a mutable ref.
`get_merged_gameweeks(season)` loads `merged_gw.csv`; `get_gameweek(season,
gameweek)` loads `gwN.csv`; `get_fixture_schedule(season)` loads the root-level
`fixtures.csv` from the exact supplied repository ref. Historical callers must
select a commit whose timestamp is strictly before the prediction deadline; the
adapter records but does not infer that temporal eligibility. Season format is
`YYYY-YY`; GW is a strict integer
from 1 to 38. The caller owns the synchronous `httpx.Client`; redirects and
retries are disabled, and `base_url`, timeout, TTL and the aware UTC retrieval
clock are injectable.

`VaastavDataset` is a frozen provenance wrapper with `season`, `dataset_name`,
optional `gameweek`, `repository_ref`, source URL, retrieval time, raw snapshot,
columns, `unsafe_columns`, `safe_feature_columns`, parsed pandas `data`, response
and `from_cache`. Pandas tables remain mutable, so retain the wrapper separately
when transforming a table. No columns are renamed or dropped. `xP`, when present,
remains in `data` and is listed in `unsafe_columns`, excluded from the convenience
safe-column list. It is potentially post-deadline upstream data and therefore is
unsafe by default; this adapter does not make feature-selection or leakage-use
decisions for other historical outcome columns.

On an actual successful remote fetch, exact `httpx.Response.content` bytes go to
RawStore first with provider `vaastav`, entity `merged_gameweeks` or `gameweek`,
the complete URL and record identity `{ref}:{season}:merged_gw` or
`{ref}:{season}:gw:{N}`. Cache namespace is `vaastav`; a fresh cache hit performs
no HTTP or raw write. CSV parsing follows that storage/cache step, so malformed
or structurally incompatible successful CSV remains auditable but never returns a
partial dataset. The parser accepts UTF-8 (including BOM) headers-only CSVs and
preserves all columns/rows; it rejects an empty body, bad UTF-8, duplicate header
names and rows with a different field count. The current upstream GW CSV uses
`round` in contemporary files, so the adapter checks requested number only when a
`GW` column is supplied rather than imposing a schema on older/newer seasons.

Errors derive from `VaastavError`: `VaastavValidationError`,
`VaastavRequestError`, `VaastavResponseError` (including `VaastavParseError`) and
`VaastavStorageError`. Transport, parsing and storage causes are chained without
including source bodies in adapter messages.

fplcache point-in-time adapter (DATA-005):

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.providers.fplcache import FPLCacheAdapter

paths = ["cache/2024/8/16/1700.json.xz", "cache/2024/8/16/1730.json.xz"]
with httpx.Client() as client:
    adapter = FPLCacheAdapter(
        client=client,
        cache=HttpCache(Path("data/interim/http_cache")),
        raw_store=RawStore(Path("data/raw")),
        repository_ref="0123456789abcdef0123456789abcdef01234567",
        snapshot_index=paths,
        ttl=None,
    )
    snapshot = adapter.get_snapshot_before(
        datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    )
```

fplcache supplies compressed `bootstrap-static` archives at
`cache/{year}/{month}/{day}/{HHMM}.json.xz`. The adapter receives a verified,
caller-supplied iterable of those paths rather than crawling an undocumented
GitHub directory API. Paths are parsed as UTC and sorted; duplicate paths or
timestamps are rejected. This index can be pinned and tested alongside the
explicit repository ref. A commit SHA is preferred for reproducible historical
backtests; mutable refs such as `main` are allowed but must not be presented as
immutable source versions.

`select_snapshot(T)` and `get_snapshot_before(T)` choose the latest archive with
`snapshot_timestamp < T`. Equality is deliberately ineligible. A snapshot after
the cutoff is never selected, even if it is closer. If no eligible archive exists,
the adapter raises `FPLCacheNoSnapshotError`; it never falls forward. All input
timestamps must be aware and normalize to UTC.

`FPLCacheSnapshot` retains the source `snapshot_timestamp`, requested
`prediction_timestamp`, operational `retrieved_at`, repository ref, archive path,
source URL, raw receipt, exact cached response, provider mapping and `from_cache`.
The archive timestamp is the source availability cutoff; the prediction timestamp
is only a selection boundary; retrieval time is when this system downloaded the
archive or its original cache-write time. These must not be interchanged. All
bootstrap fields, including prices, ownership, transfers, availability, status and
news, remain provider data. No canonical features or identities are created.

On a miss/stale read, exact compressed `.xz` bytes are persisted in RawStore before
decompression, using provider `fplcache`, entity `bootstrap_snapshot`, the full
archive URL and `{repository_ref}:{path}` as record ID. The same compressed bytes
are cached under namespace `fplcache`. Fresh hits do not issue HTTP or write raw
evidence. Decompression uses a bounded standard-library LZMA XZ stream (64 MiB
default), rejecting incomplete, concatenated or oversized data; UTF-8 JSON must
have an object root. Invalid remote payloads remain raw/cache evidence but never
return a partial bootstrap mapping.

Errors derive from `FPLCacheError`: `FPLCacheValidationError`,
`FPLCacheNoSnapshotError`, `FPLCacheRequestError`, `FPLCacheResponseError`
(including `FPLCacheParseError`) and `FPLCacheStorageError`. Causes are chained
without exposing archive bodies in adapter messages.

API-Football v3 adapter (DATA-006):

```python
from datetime import timedelta
from pathlib import Path
import httpx
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.providers.api_football import APIFootballAdapter, APIFootballQuota
from fpl_engine.data.raw_store import RawStore

with httpx.Client() as client:
    adapter = APIFootballAdapter(
        client=client,
        api_key=api_key,  # supplied outside source control
        cache=HttpCache(Path("data/interim/http_cache")),
        raw_store=RawStore(Path("data/raw")),
        quota=APIFootballQuota(daily_request_budget=80),
        ttl=timedelta(hours=1),
    )
    fixtures = adapter.get_fixtures(league=39, season=2025)
```

The synchronous caller-owned transport receives the key only in API-Football's
`x-apisports-key` header. The key is excluded from cache identity/metadata, raw
provenance, results and exceptions. The adapter supports fixtures, fixture
statistics, lineups/formations, injuries, sidelined history, transfers, coaches
and season player statistics. It preserves each native response envelope and all
unknown provider fields without canonical IDs or feature construction.

Every successful cache miss stores exact response bytes in RawStore before JSON
parsing, then publishes them to `HttpCache` under `api_football`. Fresh hits make
no network request and no raw snapshot. Non-2xx responses and non-empty provider
`errors` both fail explicitly; successful malformed responses remain auditable.
`get_all_player_statistics()` follows exactly the provider-declared pages.

`APIFootballQuota` is a caller-configured in-memory UTC-day budget. It counts
only actual transport attempts, never cache hits, and rejects a miss before a
network call when exhausted. A budget of 80 is a local reserve policy, not a
hard-coded claim about an external service quota. Available rate-limit headers
are exposed for network results. Result retrieval time records local acquisition
only; callers must apply point-in-time rules before using live or historical
provider data for backtests.

---

# Main Architecture

```text
RAW DATA
↓
CANONICAL IDENTITIES
↓
POINT-IN-TIME DATASET
↓
TEAM STRENGTH
+
PLAYER TALENT
+
TACTICAL CONTEXT
+
AVAILABILITY
↓
MINUTES MODEL
↓
PLAYER FIXTURE EVENT RATES
↓
EVENT MODELS
↓
MONTE CARLO
↓
FPL SCORING
↓
PLAYER PROJECTIONS
↓
MULTI-GW OPTIMIZER
↓
SENSITIVITY / CONFIDENCE
↓
RECOMMENDATION
```

---

# Main Objective

The primary objective is:

```text
OUT-OF-SAMPLE FPL DECISION QUALITY
```

The project prioritizes:

```text
correctness
point-in-time safety
calibration
predictive quality
decision quality
```

over unnecessary model complexity.

---

# Core Rules

The following rules are fundamental:

1. No future information may enter historical predictions.
2. Predictive models must use canonical schemas rather than provider-specific structures.
3. Missing data must not silently become zero.
4. Raw source data is immutable.
5. Player Talent and Team Environment are separate concepts.
6. Minutes are predicted by a dedicated probabilistic model.
7. Football events are predicted before FPL points.
8. Monte Carlo preserves important match-level correlations.
9. FPL scoring rules are external configuration.
10. FPL optimizer rules are external configuration.
11. Rolling a free transfer is always a valid optimizer action.
12. Advanced models must beat documented baselines before promotion.
13. Walk-forward backtesting is mandatory.
14. LLMs do not perform mathematical prediction or optimization.

See:

```text
docs/06_PROJECT/decisions.md
```

for the complete architectural decision log.

---

# Repository Structure

```text
fpl-prediction-engine/

├── docs/
│
│   ├── 00_PROJECT_CONTEXT.md
│
│   ├── 01_DATA/
│   │   ├── data_sources.yaml
│   │   ├── data_requirements.yaml
│   │   ├── leakage_rules.md
│   │   └── identity_resolution.md
│
│   ├── 02_MODELS/
│   │   ├── model_pipeline.yaml
│   │   ├── team_strength.md
│   │   ├── minutes.md
│   │   ├── player_talent.md
│   │   ├── tactical_context.md
│   │   └── events.md
│
│   ├── 03_SIMULATION/
│   │   ├── monte_carlo.md
│   │   └── scoring_rules.yaml
│
│   ├── 04_OPTIMIZER/
│   │   ├── optimizer.md
│   │   └── fpl_rules.yaml
│
│   ├── 05_VALIDATION/
│   │   ├── backtesting.md
│   │   └── metrics.md
│
│   └── 06_PROJECT/
│       ├── roadmap.yaml
│       └── decisions.md
│
├── data/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   └── snapshots/
│
├── src/
├── tests/
└── README.md
```

---

# Documentation Priority

Before implementing code, read documentation in this order.

## 1. Project context

```text
docs/00_PROJECT_CONTEXT.md
```

Defines:

```text
project goal
overall architecture
main modelling philosophy
```

---

## 2. Architectural decisions

```text
docs/06_PROJECT/decisions.md
```

Defines decisions that must not be silently changed.

---

## 3. Roadmap

```text
docs/06_PROJECT/roadmap.yaml
```

Defines:

```text
implementation order
task IDs
dependencies
outputs
tests
Definition of Done
```

Implementation should normally follow this file.

---

## 4. Relevant module specification

For example:

Task:

```text
MIN-003
```

should read:

```text
docs/02_MODELS/minutes.md
docs/02_MODELS/model_pipeline.yaml
docs/01_DATA/leakage_rules.md
```

before implementation.

---

# Codex Workflow

The repository is designed to be implemented incrementally using small Codex tasks.

Do NOT ask Codex to:

```text
build the whole project
```

in one run.

Preferred workflow:

```text
one roadmap task
↓
implementation
↓
tests
↓
review
↓
next task
```

---

# First Codex Task

Start with:

```text
CORE-001
```

from:

```text
docs/06_PROJECT/roadmap.yaml
```

Recommended Codex prompt:

```text
Read:
- README.md
- docs/00_PROJECT_CONTEXT.md
- docs/06_PROJECT/decisions.md
- docs/06_PROJECT/roadmap.yaml

Implement only task CORE-001.

Do not implement later roadmap tasks.

Follow documented architecture and interfaces.

Add/update relevant tests.

Run the relevant tests before finishing.

At the end report:
- files changed
- tests run
- test results
- any specification conflicts
```

---

# Generic Codex Prompt

For later tasks use:

```text
Read:
- README.md
- docs/00_PROJECT_CONTEXT.md
- docs/06_PROJECT/decisions.md
- docs/06_PROJECT/roadmap.yaml
- specification files relevant to TASK_ID

Implement only TASK_ID.

Requirements:
- follow documented interfaces,
- do not implement unrelated future tasks,
- preserve point-in-time safety,
- do not introduce undocumented architectural changes,
- add/update relevant tests,
- run tests before finishing.

At the end report:
- files changed,
- implementation summary,
- tests run,
- test results,
- any unresolved issues,
- any conflicts with the specification.
```

Replace:

```text
TASK_ID
```

with for example:

```text
DATA-001
MODEL-001
MIN-001
SIM-001
OPT-001
```

---

# Important Codex Rule

Codex should never silently redesign the architecture.

If existing code conflicts with documentation:

```text
REPORT THE CONFLICT
```

rather than inventing a new design.

If a task appears to require changing an accepted architectural decision:

```text
STOP THAT PART OF IMPLEMENTATION
AND REPORT WHICH DECISION IS AFFECTED
```

---

# Data Strategy

The core project follows a:

```text
FREE-FIRST
```

data architecture.

Primary sources:

```text
Official FPL API
Vaastav/Fantasy-Premier-League
fplcache
API-Football Free
StatsBomb Open Data
football-data.co.uk
local FPL snapshots
manual context
```

A paid provider is not required for the core system.

See:

```text
docs/01_DATA/data_sources.yaml
```

---

# Canonical Data Principle

Models must never directly consume:

```text
provider-specific JSON
```

Expected architecture:

```text
PROVIDER
↓
ADAPTER
↓
CANONICAL DATA
↓
FEATURES
↓
MODEL
```

This allows data providers to be changed without rewriting models.

---

# Point-in-Time Safety

Historical predictions must contain only information that was actually available at the prediction timestamp.

Canonical rule:

```text
feature_known_at <= prediction_timestamp
```

Historical FPL deadline is the default prediction timestamp.

Forbidden examples:

```text
actual target-match lineup
future injury news
future price
future manager
future transfer
future formation
future fixture reschedule
target-match statistics
```

See:

```text
docs/01_DATA/leakage_rules.md
```

and:

```text
docs/05_VALIDATION/backtesting.md
```

---

# Storage

Recommended analytical storage:

```text
Parquet
+
DuckDB
```

Raw provider responses:

```text
data/raw/
```

should be immutable and append-only.

Current point-in-time snapshots:

```text
data/snapshots/
```

should also be append-only.

---

# Team Strength

Primary purpose:

```text
estimate team attack and defence
for a specific fixture
```

Preferred statistical core:

```text
Poisson
Dixon-Coles
```

with:

```text
xG
time decay
priors
opponent adjustment
home advantage
regime context
```

Complex ML correction is optional and requires backtesting evidence.

Specification:

```text
docs/02_MODELS/team_strength.md
```

---

# Player Talent

Player historical production must be separated from team environment.

Example:

```text
historical xG/90
```

is not treated as a permanent constant after a transfer.

Talent modelling considers:

```text
player rates
team shares
role
team quality
opposition
league strength
transfer context
```

Specification:

```text
docs/02_MODELS/player_talent.md
```

---

# Tactical Context

Tactical context includes:

```text
role
formation
manager
club change
league change
set pieces
squad competition
regime changes
```

Tactical role is not the same as FPL position.

Specification:

```text
docs/02_MODELS/tactical_context.md
```

---

# Minutes Model

The Minutes Model predicts a probability distribution, not only a point estimate.

Required outputs include:

```text
P(appearance)
P(start)
expected_minutes
P(60+)
P(75+)
P(90)
minute_distribution
uncertainty
```

Specification:

```text
docs/02_MODELS/minutes.md
```

---

# Event Models

Football events include:

```text
goals
assists
clean sheets
saves
penalty saves
defensive contributions
cards
BPS / bonus
```

Events must remain coherent with the match.

Example:

```text
team scores 2
```

must not produce:

```text
players collectively scoring 4
```

Specification:

```text
docs/02_MODELS/events.md
```

---

# Monte Carlo

Default initial configuration:

```text
~10,000 simulations per fixture
```

but simulation count must be validated through convergence testing.

Monte Carlo should preserve correlations such as:

```text
team goals ↔ player goals
team goals ↔ assists
team clean sheet ↔ defender clean sheets
opponent shots ↔ goalkeeper saves
goals/assists ↔ bonus
```

Specification:

```text
docs/03_SIMULATION/monte_carlo.md
```

---

# FPL Scoring

Football events are converted into FPL points using season-specific configuration.

Configuration:

```text
docs/03_SIMULATION/scoring_rules.yaml
```

Predictive models should not contain hardcoded FPL scoring values.

---

# Player Projection Outputs

Expected final player outputs include:

```text
xMins

P(start)
P(60+)
P(90)

expected goals
expected assists
clean-sheet probability

GW+1 EV
3GW EV
6GW EV

median FPL points

P(blank)
P(return)

P(5+)
P(8+)
P(10+)
P(15+)

uncertainty
```

---

# Optimizer

The optimizer decides:

```text
roll FT
transfer
multiple transfers
hits
starting XI
bench order
captain
vice-captain
Wildcard
Free Hit
Bench Boost
Triple Captain
```

Default objective:

```text
maximize expected FPL points
```

with a default planning horizon of:

```text
6 Gameweeks
```

Specification:

```text
docs/04_OPTIMIZER/optimizer.md
```

Rules:

```text
docs/04_OPTIMIZER/fpl_rules.yaml
```

---

# Recommendation Confidence

Recommendations must not be presented as equally certain.

Sensitivity analysis should perturb uncertain model inputs and rerun optimization.

Candidate default:

```text
500 runs
```

Output:

```text
action_selection_frequency
decision_margin
recommendation_confidence
```

A marginal recommendation should be identified explicitly.

---

# Validation

All models require:

```text
baseline
walk-forward backtest
out-of-sample metrics
calibration
segment analysis
```

Advanced methods are promoted only when they provide measurable value.

Specifications:

```text
docs/05_VALIDATION/backtesting.md
docs/05_VALIDATION/metrics.md
```

---

# Permanent Baselines

Do not remove baseline implementations after better models are added.

Examples:

```text
Team Strength:
league average
rolling goals
rolling xG
simple Poisson

Minutes:
previous-match minutes
rolling-5 minutes
rolling-5 start rate

Talent:
season-to-date per90
EWMA per90

Optimizer:
roll/no-transfer
greedy 1GW
static 6GW
```

Baselines help detect regressions.

---

# Production Philosophy

The system should eventually support a workflow similar to:

```text
refresh data
↓
create snapshot
↓
update canonical tables
↓
build features
↓
run models
↓
simulate fixtures
↓
aggregate projections
↓
load user squad
↓
run optimizer
↓
run sensitivity
↓
return recommendation
```

The LLM may then explain the structured result.

---

# What the LLM Should Receive

Good:

```text
player projections
top transfer candidates
optimizer output
decision alternatives
confidence
structured diagnostics
```

Bad:

```text
millions of raw event rows
raw API responses
10,000 raw simulation rows per player
```

The computational system handles raw data.

The LLM handles explanation.

---

# Development Rule

Always follow:

```text
SIMPLE CORRECT BASELINE
↓
BACKTEST
↓
IMPROVED MODEL
↓
BACKTEST
↓
PROMOTE ONLY IF BETTER
```

Do not follow:

```text
ADD COMPLEXITY
BECAUSE IT SOUNDS ADVANCED
```

---

# Definition of Done

A roadmap task is finished only when:

```text
implementation is complete
tests exist
tests pass
interfaces match documentation
no point-in-time rule is violated
```

---

# Final Principle

The project should optimize for:

```text
CORRECTNESS
REPRODUCIBILITY
CALIBRATION
OUT-OF-SAMPLE PERFORMANCE
```

not architectural complexity.

The governing rule is:

```text
NO LEAKAGE.
NO HINDSIGHT.
NO SILENT ASSUMPTIONS.
NO COMPLEXITY WITHOUT MEASURABLE VALUE.
```

## Current-season prediction

Materialize current point-in-time data and generate canonical 1/3/6 Gameweek
projections with the production setting of 10,000 simulations per fixture:

```powershell
.venv\Scripts\python.exe -m fpl_engine predict-current --season 2026/27 --gameweek <GW>
```

Add `--squad-state data\local\squad-state.json` to run the existing non-mutating
shadow decision flow from the generated projections and candidate pool. Greedy
1GW is the experimental default; Optimizer V1 and V2 are comparison challengers.
See [current prediction](docs/05_VALIDATION/current_prediction.md) for input,
provenance, diagnostic simulation, and output details.

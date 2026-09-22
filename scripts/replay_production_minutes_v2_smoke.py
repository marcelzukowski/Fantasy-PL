from __future__ import annotations

import gzip
import json
import os
import lzma
from datetime import datetime, timezone
from pathlib import Path
import importlib

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)

from fpl_engine.current import (
    CurrentDataSource,
    CurrentPipelineConfig,
    CurrentPredictionPipeline,
    CurrentSourceData,
    CurrentSourceRecord,
)
from fpl_engine.types import PredictionContext


ROOT = Path.cwd()

SEED = int(
    os.environ[
        "CAPTAIN_REPLAY_SEED"
    ]
)

OLD_RUN_ID = os.environ[
    "CAPTAIN_OLD_RUN_ID"
]

OLD_RUN = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / OLD_RUN_ID
)

PROVENANCE = OLD_RUN / "source_provenance.json"
CONTEXT_PATH = OLD_RUN / "prediction_context.json"

STAMP = datetime.now(timezone.utc).strftime(
    "%Y%m%dT%H%M%SZ"
)

REPLAY_ROOT = (
    ROOT
    / "scratch"
    / "decision"
    / f"production_minutes_v2_smoke_seed{SEED}_{STAMP}"
)

REPLAY_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

REPORT_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / f"production_minutes_v2_smoke_report_seed{SEED}.txt"
)


TARGETS = {
    "Palmer":
        "ply_19d5ba62-d425-51e6-b30b-de90a5adf4e8",
    "Szoboszlai":
        "ply_3db58329-d31f-5ed9-9e52-a2ef02ad8d2c",
    "Groß":
        "ply_5a9093a1-ee9b-56b3-9d91-c976cc8f2046",
    "Haaland":
        "ply_f5b0178d-f837-5554-9cd4-723b48c97826",
    "B.Fernandes":
        "ply_e12222fa-6342-5394-a9ee-d1d9e71e96a5",
}


XI_NAMES = (
    "Sels",
    "Maatsen",
    "Justin",
    "De Cuyper",
    "Groß",
    "Tavernier",
    "B.Fernandes",
    "Szoboszlai",
    "Palmer",
    "Calvert-Lewin",
    "Haaland",
)


def dt(value):

    if value is None:
        return None

    parsed = datetime.fromisoformat(
        str(value).replace(
            "Z",
            "+00:00",
        )
    )

    return parsed.astimezone(
        timezone.utc
    )


def read_payload(
    snapshot_id,
    source,
):

    raw_root = (
        ROOT
        / "data"
        / "raw"
        / source
    )

    if not raw_root.exists():

        raw_root = (
            ROOT
            / "data"
            / "raw"
        )

    matches = sorted(
        path
        for path in raw_root.rglob(
            "payload.bin"
        )
        if path.parent.name
        == snapshot_id
    )

    if not matches:

        raise RuntimeError(
            f"snapshot {snapshot_id}: "
            "payload not found"
        )

    body = matches[0].read_bytes()

    attempts = [body]

    try:
        attempts.append(
            gzip.decompress(body)
        )
    except Exception:
        pass

    try:
        attempts.append(
            lzma.decompress(body)
        )
    except Exception:
        pass

    for candidate in attempts:

        try:

            return json.loads(
                candidate.decode(
                    "utf-8"
                )
            )

        except Exception:
            continue

    raise RuntimeError(
        f"cannot decode snapshot "
        f"{snapshot_id}"
    )


def recover_snapshot_id(row):

    snapshot_id = row.get(
        "raw_snapshot_id"
    )

    if snapshot_id:

        return str(
            snapshot_id
        )

    checksum = str(
        row.get(
            "checksum",
            "",
        )
    )

    if not checksum:

        raise RuntimeError(
            f"{row['entity']} has "
            "neither raw_snapshot_id "
            "nor checksum"
        )

    raw_root = (
        ROOT
        / "data"
        / "raw"
        / row["source"]
    )

    if not raw_root.exists():

        raw_root = (
            ROOT
            / "data"
            / "raw"
        )

    candidates = []

    for meta_path in raw_root.rglob(
        "snapshot.metadata.json"
    ):

        try:

            meta = json.loads(
                meta_path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:

            continue

        if str(
            meta.get(
                "checksum",
                "",
            )
        ) != checksum:

            continue

        payload = (
            meta_path.parent
            / "payload.bin"
        )

        if not payload.exists():

            continue

        candidates.append(
            meta_path.parent.name
        )

    candidates = sorted(
        set(
            candidates
        )
    )

    if not candidates:

        raise RuntimeError(
            f"{row['entity']}: "
            f"no RawStore payload for "
            f"checksum={checksum}"
        )

    recovered = candidates[0]

    print(
        "[replay] recovered cached "
        f"{row['entity']} -> "
        f"{recovered}"
    )

    return recovered


def build_record(row):

    snapshot_id = (
        recover_snapshot_id(
            row
        )
    )

    return CurrentSourceRecord(
        source=row["source"],
        entity=row["entity"],
        payload=read_payload(
            snapshot_id,
            row["source"],
        ),
        known_at=dt(
            row["known_at"]
        ),
        retrieved_at=dt(
            row["retrieved_at"]
        ),
        checksum=row["checksum"],
        source_version=row[
            "source_version"
        ],
        raw_snapshot_id=snapshot_id,
        cache_key=row.get(
            "cache_key"
        ),
        from_cache=bool(
            row.get(
                "from_cache",
                False,
            )
        ),
        source_snapshot_timestamp=dt(
            row.get(
                "source_snapshot_timestamp"
            )
        ),
    )


def rows(path):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(raw, list):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "projections",
        "fixtures",
        "minutes",
    ):

        value = raw.get(key)

        if isinstance(
            value,
            list,
        ):
            return value

    raise RuntimeError(
        f"cannot find rows in {path}"
    )


# ------------------------------------------------------------
# Rebuild EXACT pre-deadline source
# ------------------------------------------------------------

provenance = json.loads(
    PROVENANCE.read_text(
        encoding="utf-8"
    )
)

records = [
    build_record(row)
    for row in provenance
]

bootstrap = next(
    row
    for row in records
    if "bootstrap"
    in row.entity
)

fixtures = next(
    row
    for row in records
    if (
        "fixture" in row.entity
        and not row.entity.startswith(
            "event_live"
        )
    )
)

live = tuple(
    row
    for row in records
    if row.entity.startswith(
        "event_live"
    )
)

optional = tuple(
    row
    for row in records
    if (
        row is not bootstrap
        and row is not fixtures
        and row not in live
    )
)

materialized = CurrentSourceData(
    bootstrap=bootstrap,
    fixtures=fixtures,
    event_live=live,
    optional=optional,
)


# ------------------------------------------------------------
# Exact original prediction context
# ------------------------------------------------------------

context_raw = json.loads(
    CONTEXT_PATH.read_text(
        encoding="utf-8"
    )
)

context_raw["prediction_timestamp"] = dt(
    context_raw["prediction_timestamp"]
)

context = PredictionContext.model_validate(
    context_raw
)


class OfflineSource:

    def refresh(
        self,
        context,
    ):

        raise RuntimeError(
            "NETWORK REFRESH MUST NOT "
            "BE CALLED IN OFFLINE REPLAY"
        )


# ------------------------------------------------------------
# FIXED replay
# ------------------------------------------------------------

print(
    "[smoke] Minutes runtime="
    "PRODUCTION_UNPATCHED"
)

pipeline = CurrentPredictionPipeline(
    OfflineSource(),
    project_root=ROOT,
    config=CurrentPipelineConfig(
        canonical_database=(
            REPLAY_ROOT
            / "current.duckdb"
        ),
        output_root=(
            REPLAY_ROOT
            / "output"
        ),
        simulations_per_fixture=256,
        random_seed=SEED,
        history_seasons=(
            "2024-25",
            "2025-26",
        ),
        projection_horizon_gameweeks=6,
    ),
    progress=lambda message: print(
        "[replay]",
        message,
    ),
)

result = pipeline.run(
    context,
    materialized_source=materialized,
    market_quotes=(),
)

FIXED_RUN = result.run_directory


# ------------------------------------------------------------
# Load OLD / FIXED artifacts
# ------------------------------------------------------------

old_proj = {
    str(row["player_id"]): row
    for row in rows(
        OLD_RUN
        / "player_projections.json"
    )
}

fixed_proj = {
    str(row["player_id"]): row
    for row in rows(
        FIXED_RUN
        / "player_projections.json"
    )
}


def ev1(row):

    for key in (
        "ev_next_1",
        "expected_points_next_1",
        "weighted_ev_next_1",
    ):

        if key in row:

            return float(
                row[key]
            )

    raise RuntimeError(
        "GW1 EV field missing; "
        f"keys={sorted(row)}"
    )


def load_fixture_maps(run):

    fixtures = rows(
        run
        / "fixture_horizon.json"
    )

    by_id = {
        str(row["fixture_id"]): row
        for row in fixtures
    }

    return by_id


def load_minutes(run):

    return rows(
        run
        / "minutes.json"
    )


def gw4_minute(
    run,
    player_id,
):

    fixture_map = load_fixture_maps(
        run
    )

    matches = []

    for row in load_minutes(run):

        if str(
            row.get("player_id")
        ) != player_id:
            continue

        fid = str(
            row["fixture_id"]
        )

        fixture = fixture_map[
            fid
        ]

        gw = (
            fixture.get(
                "target_gameweek"
            )
            or fixture.get(
                "gameweek"
            )
            or fixture.get(
                "event"
            )
        )

        if int(gw) == 4:

            matches.append(
                row
            )

    if len(matches) != 1:

        raise RuntimeError(
            f"{player_id}: "
            f"GW4 minute rows="
            f"{len(matches)}"
        )

    return matches[0]


def own_team_xg(
    run,
    player_id,
):

    fixture_map = load_fixture_maps(
        run
    )

    minute = gw4_minute(
        run,
        player_id,
    )

    fixture = fixture_map[
        str(
            minute[
                "fixture_id"
            ]
        )
    ]

    players = rows(
        run
        / "current_players.json"
    )

    player = next(
        row
        for row in players
        if str(
            row["player_id"]
        ) == player_id
    )

    team_id = str(
        player["team_id"]
    )

    home = str(
        fixture[
            "home_team_id"
        ]
    )

    away = str(
        fixture[
            "away_team_id"
        ]
    )

    strength = next(
        row
        for row in rows(
            run
            / "team_strength.json"
        )
        if (
            str(
                row[
                    "home_team_id"
                ]
            ) == home
            and str(
                row[
                    "away_team_id"
                ]
            ) == away
        )
    )

    if team_id == home:

        return float(
            strength[
                "expected_home_goals"
            ]
        )

    if team_id == away:

        return float(
            strength[
                "expected_away_goals"
            ]
        )

    raise RuntimeError(
        "player team not in fixture"
    )


# ------------------------------------------------------------
# Captaincy restricted to actual XI, MID/FWD
# ------------------------------------------------------------

plan = json.loads(
    (
        ROOT
        / "scratch"
        / "decision"
        / "final_wc_playing_plan.json"
    ).read_text(
        encoding="utf-8"
    )
)

base = next(
    row
    for row in plan["candidates"]
    if "BASE_CAND5"
    in row["labels"]
)

base_ids = set(
    base["player_ids"]
)

player_rows = rows(
    OLD_RUN
    / "current_players.json"
)

by_id = {
    str(row["player_id"]): row
    for row in player_rows
}


def resolve_base_name(name):

    matches = [
        pid
        for pid in base_ids
        if (
            pid in by_id
            and by_id[pid][
                "display_name"
            ] == name
        )
    ]

    if len(matches) != 1:

        raise RuntimeError(
            f"{name}: "
            f"BASE matches={matches}"
        )

    return matches[0]


xi_ids = tuple(
    resolve_base_name(name)
    for name in XI_NAMES
)

captain_pool = tuple(
    pid
    for pid in xi_ids
    if by_id[pid]["position"]
    in {
        "MID",
        "FWD",
    }
)


def best_pair(
    run,
    projections,
):

    ev = {
        pid: ev1(
            projections[pid]
        )
        for pid in captain_pool
    }

    papp = {
        pid: float(
            gw4_minute(
                run,
                pid,
            )[
                "p_appearance"
            ]
        )
        for pid in captain_pool
    }

    best = None

    for captain in captain_pool:

        for vice in captain_pool:

            if captain == vice:
                continue

            bonus = (
                ev[captain]
                + (
                    1.0
                    - papp[captain]
                )
                * ev[vice]
            )

            candidate = (
                bonus,
                ev[captain],
                ev[vice],
                captain,
                vice,
            )

            if (
                best is None
                or candidate
                > best
            ):

                best = candidate

    return best


old_pair = best_pair(
    OLD_RUN,
    old_proj,
)

fixed_pair = best_pair(
    FIXED_RUN,
    fixed_proj,
)


# ------------------------------------------------------------
# Compact report
# ------------------------------------------------------------

lines = []

lines.append(
    "============================================================"
)
lines.append(
    "CAPTAIN xG FIX | CONTROLLED A/B"
)
lines.append(
    f"same pre-deadline snapshots | 256 sims | seed {SEED}"
)
lines.append(
    "============================================================"
)
lines.append("")

lines.append(
    f"OLD   : {OLD_RUN.name}"
)

lines.append(
    f"FIXED : {FIXED_RUN}"
)

lines.append("")

lines.append(
    f"{'PLAYER':<18}"
    f"{'OLD xG':>9}"
    f"{'FIX xG':>9}"
    f"{'DXG':>9}"
    f"{'OLD EV':>9}"
    f"{'FIX EV':>9}"
    f"{'DEV':>9}"
)

for name, pid in TARGETS.items():

    old_xg = own_team_xg(
        OLD_RUN,
        pid,
    )

    new_xg = own_team_xg(
        FIXED_RUN,
        pid,
    )

    old_ev = ev1(
        old_proj[
            pid
        ]
    )

    new_ev = ev1(
        fixed_proj[
            pid
        ]
    )

    lines.append(
        f"{name:<18}"
        f"{old_xg:>9.3f}"
        f"{new_xg:>9.3f}"
        f"{new_xg-old_xg:>+9.3f}"
        f"{old_ev:>9.3f}"
        f"{new_ev:>9.3f}"
        f"{new_ev-old_ev:>+9.3f}"
    )


def pair_text(pair):

    bonus, c_ev, v_ev, c, v = (
        pair
    )

    return (
        f"C={by_id[c]['display_name']} "
        f"VC={by_id[v]['display_name']} "
        f"C_EV={c_ev:.3f} "
        f"VC_EV={v_ev:.3f} "
        f"bonus={bonus:.3f}"
    )


lines.append("")
lines.append(
    "CAPTAINCY | actual XI | MID/FWD only"
)
lines.append(
    "OLD   " + pair_text(
        old_pair
    )
)
lines.append(
    "FIXED " + pair_text(
        fixed_pair
    )
)

lines.append("")
lines.append(
    "=== END ==="
)

report = "\n".join(
    lines
)

REPORT_PATH.write_text(
    report + "\n",
    encoding="utf-8",
)

print()
print(report)

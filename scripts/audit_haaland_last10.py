from __future__ import annotations

import gzip
import json
import lzma
import re
from datetime import datetime, timezone
from pathlib import Path

from fpl_engine.current_history import (
    load_strict_historical_context,
)
from fpl_engine.features.minutes_dataset import (
    MinutesObservation,
)
from fpl_engine.models.minutes import (
    MinutesContext,
    MinutesModel,
)


ROOT = Path.cwd()

HAALAND = (
    "ply_f5b0178d-f837-5554-9cd4-723b48c97826"
)

OLD_RUN = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / "20260912T100351Z"
)


def utc(value):
    x = datetime.fromisoformat(
        str(value).replace(
            "Z",
            "+00:00",
        )
    )
    return x.astimezone(
        timezone.utc
    )


def read_payload(snapshot_id):

    matches = [
        p
        for p in (
            ROOT
            / "data"
            / "raw"
        ).rglob("payload.bin")
        if p.parent.name == snapshot_id
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"{snapshot_id}: "
            f"payloads={len(matches)}"
        )

    body = matches[0].read_bytes()

    candidates = [body]

    for decoder in (
        gzip.decompress,
        lzma.decompress,
    ):
        try:
            candidates.append(
                decoder(body)
            )
        except Exception:
            pass

    for raw in candidates:
        try:
            return json.loads(
                raw.decode("utf-8")
            )
        except Exception:
            pass

    raise RuntimeError(
        f"cannot decode {snapshot_id}"
    )


context_raw = json.loads(
    (
        OLD_RUN
        / "prediction_context.json"
    ).read_text(
        encoding="utf-8"
    )
)

AT = utc(
    context_raw[
        "prediction_timestamp"
    ]
)


players = json.loads(
    (
        OLD_RUN
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

player = next(
    row
    for row in players
    if row["player_id"] == HAALAND
)

provider_id = str(
    player["provider_id"]
)

provider_team = str(
    player["provider_team_id"]
)


provenance = json.loads(
    (
        OLD_RUN
        / "source_provenance.json"
    ).read_text(
        encoding="utf-8"
    )
)

by_entity = {
    row["entity"]: row
    for row in provenance
}

fixtures_record = next(
    row
    for row in provenance
    if "fixture" in row["entity"]
)

fixtures_payload = read_payload(
    fixtures_record[
        "raw_snapshot_id"
    ]
)

if isinstance(
    fixtures_payload,
    dict,
):
    fixtures_payload = (
        fixtures_payload.get(
            "fixtures",
            fixtures_payload.get(
                "data",
                [],
            ),
        )
    )


# ------------------------------------------------------------
# STRICT previous-season observations
# ------------------------------------------------------------

strict = load_strict_historical_context(
    ROOT,
    (
        "2024-25",
        "2025-26",
    ),
    prediction_timestamp=AT,
)

observations = list(
    strict.minutes.get(
        HAALAND,
        (),
    )
)

source_by_fixture = {
    row.fixture_id: "STRICT"
    for row in observations
}


# ------------------------------------------------------------
# Current GW1-GW3 observations from exact snapshots
# ------------------------------------------------------------

for gw in (1, 2, 3):

    record = by_entity[
        f"event_live_{gw}"
    ]

    payload = read_payload(
        record[
            "raw_snapshot_id"
        ]
    )

    element = next(
        row
        for row in payload["elements"]
        if str(
            row.get("id")
        ) == provider_id
    )

    stats = element["stats"]

    fixture_candidates = [
        row
        for row in fixtures_payload
        if int(
            row.get("event") or 0
        ) == gw
        and provider_team
        in {
            str(row.get("team_h")),
            str(row.get("team_a")),
        }
    ]

    if len(
        fixture_candidates
    ) != 1:

        raise RuntimeError(
            f"GW{gw}: "
            f"fixtures="
            f"{len(fixture_candidates)}"
        )

    fixture = fixture_candidates[0]

    fixture_id = (
        f"current_gw{gw}_"
        f"{fixture['id']}"
    )

    observation = MinutesObservation(
        HAALAND,
        fixture_id,
        utc(
            fixture[
                "kickoff_time"
            ]
        ),
        utc(
            record[
                "known_at"
            ]
        ),
        int(
            stats[
                "minutes"
            ]
        ),
        bool(
            int(
                stats[
                    "starts"
                ]
            )
        ),
    )

    observations.append(
        observation
    )

    source_by_fixture[
        fixture_id
    ] = f"GW{gw}"


observations.sort(
    key=lambda row: (
        row.kickoff,
        row.fixture_id,
    )
)

last10 = observations[-10:]

model = MinutesModel()

weights = model._weights(
    len(last10)
)

appearance_evidence = sum(
    weight * row.appeared
    for row, weight
    in zip(
        last10,
        weights,
    )
)

total_evidence = sum(
    weights
)

raw_p_app = (
    appearance_evidence
    + model.config.appearance_prior_alpha
) / (
    total_evidence
    + model.config.appearance_prior_alpha
    + model.config.appearance_prior_beta
)

start_evidence = sum(
    weight * row.started
    for row, weight
    in zip(
        last10,
        weights,
    )
)

raw_start_given_app = (
    start_evidence
    + model.config.start_prior_alpha
) / (
    appearance_evidence
    + model.config.start_prior_alpha
    + model.config.start_prior_beta
)


print()
print(
    "============================================"
)
print(
    "LAST 10 OBSERVATIONS"
)
print(
    "============================================"
)

print(
    f"{'#':<3}"
    f"{'SOURCE':<8}"
    f"{'DATE':<12}"
    f"{'MIN':>5}"
    f"{'APP':>6}"
    f"{'START':>7}"
    f"{'WEIGHT':>9}"
)

for i, (
    row,
    weight,
) in enumerate(
    zip(
        last10,
        weights,
    ),
    start=1,
):

    print(
        f"{i:<3}"
        f"{source_by_fixture.get(row.fixture_id, 'STRICT'):<8}"
        f"{row.kickoff.date().isoformat():<12}"
        f"{row.minutes:>5}"
        f"{int(row.appeared):>6}"
        f"{int(row.started):>7}"
        f"{weight:>9.3f}"
    )


print()
print(
    "============================================"
)
print(
    "RAW HURDLE"
)
print(
    "============================================"
)

print(
    f"total evidence      : "
    f"{total_evidence:.3f}"
)

print(
    f"appearance evidence : "
    f"{appearance_evidence:.3f}"
)

print(
    f"raw p_appearance    : "
    f"{raw_p_app:.4f}"
)

print(
    f"start evidence      : "
    f"{start_evidence:.3f}"
)

print(
    f"raw P(start|appear) : "
    f"{raw_start_given_app:.4f}"
)


# ------------------------------------------------------------
# Compare with final calibrated production output
# ------------------------------------------------------------

report = (
    ROOT
    / "scratch"
    / "decision"
    / "captain_xg_ab_report_seed42.txt"
).read_text(
    encoding="utf-8"
)

fixed_path = re.search(
    r"^FIXED\s*:\s*(.+)$",
    report,
    flags=re.MULTILINE,
).group(1).strip()

fixed_run = Path(
    fixed_path
)

minutes_rows = json.loads(
    (
        fixed_run
        / "minutes.json"
    ).read_text(
        encoding="utf-8"
    )
)

fixture_rows = json.loads(
    (
        fixed_run
        / "fixture_horizon.json"
    ).read_text(
        encoding="utf-8"
    )
)

fixture_by_id = {
    row["fixture_id"]: row
    for row in fixture_rows
}

gw4 = next(
    row
    for row in minutes_rows
    if (
        row["player_id"]
        == HAALAND
        and int(
            fixture_by_id[
                row["fixture_id"]
            ]["target_gameweek"]
        ) == 4
    )
)


print()
print(
    "============================================"
)
print(
    "FINAL CALIBRATED GW4"
)
print(
    "============================================"
)

print(
    f"p_appearance        : "
    f"{float(gw4['p_appearance']):.4f}"
)

print(
    f"p_start             : "
    f"{float(gw4['p_start']):.4f}"
)

print(
    f"expected_minutes    : "
    f"{float(gw4['expected_minutes']):.2f}"
)

print()
print(
    "DNP rows in last10  :",
    sum(
        not row.appeared
        for row in last10
    ),
)

print(
    "bench rows in last10:",
    sum(
        row.appeared
        and not row.started
        for row in last10
    ),
)

print()
print(
    "=== END ==="
)

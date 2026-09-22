from pathlib import Path
import json
import statistics


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


players = json.loads(
    (
        RUN / "current_players.json"
    ).read_text(
        encoding="utf-8-sig"
    )
)

events = json.loads(
    (
        RUN / "event_projections.json"
    ).read_text(
        encoding="utf-8-sig"
    )
)


meta = {
    str(row["player_id"]): row
    for row in players
}


def name(pid):

    row = meta.get(
        pid,
        {}
    )

    return str(
        row.get("display_name")
        or row.get("web_name")
        or row.get("name")
        or pid
    )


def position(pid):

    row = meta.get(
        pid,
        {}
    )

    value = (
        row.get("position")
        or row.get("position_name")
    )

    if value:

        value = str(
            value
        ).upper()

        return {
            "GKP": "GK",
            "GOALKEEPER": "GK",
            "DEFENDER": "DEF",
            "MIDFIELDER": "MID",
            "FORWARD": "FWD",
        }.get(
            value,
            value,
        )

    return {
        1: "GK",
        2: "DEF",
        3: "MID",
        4: "FWD",
        "1": "GK",
        "2": "DEF",
        "3": "MID",
        "4": "FWD",
    }.get(
        row.get("element_type"),
        "?",
    )


rates_by_player = {}


for fixture in events:

    for side_name in (
        "home",
        "away",
    ):

        for row in (
            fixture
            .get(side_name, {})
            .get("players", [])
        ):

            rates = row.get(
                "rates",
                {},
            )

            pid = (
                row.get("player_id")
                or rates.get("player_id")
            )

            rate = rates.get(
                "fixture_npxg_per90"
            )

            if (
                pid is None
                or rate is None
            ):
                continue

            pid = str(pid)

            rates_by_player.setdefault(
                pid,
                [],
            ).append(
                float(rate)
            )


summary = []

for pid, values in (
    rates_by_player.items()
):

    if position(pid) != "FWD":
        continue

    summary.append(
        (
            statistics.median(
                values
            ),
            max(values),
            min(values),
            name(pid),
            pid,
        )
    )


summary.sort(
    reverse=True
)


print(
    "=== FWD npxG/90 TOP 20 ==="
)

for median, high, low, player, pid in summary[:20]:

    marker = (
        "  <== HAALAND"
        if player == "Haaland"
        else ""
    )

    print(
        f"{player:<24} "
        f"median={median:.3f} "
        f"min={low:.3f} "
        f"max={high:.3f}"
        f"{marker}"
    )


haaland = [
    row
    for row in summary
    if row[3] == "Haaland"
]

print()

if haaland:

    rank = (
        summary.index(
            haaland[0]
        )
        + 1
    )

    print(
        "Haaland FWD rank:",
        rank,
        "/",
        len(summary),
    )


print()
print(
    "=== SOURCE REFERENCES ==="
)


terms = (
    "fixture_npxg_per90",
    "raw_expected_npxg",
    "allocated_player_goals",
)


for path in sorted(
    Path("src").rglob("*.py")
):

    text = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    lines = text.splitlines()

    hits = []

    for i, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            term in line
            for term in terms
        ):

            hits.append(i)


    if not hits:
        continue


    print()
    print(path)

    shown = set()

    for hit in hits:

        start = max(
            1,
            hit - 4,
        )

        end = min(
            len(lines),
            hit + 6,
        )

        for number in range(
            start,
            end + 1,
        ):

            if number in shown:
                continue

            shown.add(
                number
            )

            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )

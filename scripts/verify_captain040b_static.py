from pathlib import Path


path = Path(
    "scripts/screen_wildcard_timing.py"
)

text = path.read_text(
    encoding="utf-8-sig"
)


checks = {
    "appearance helper": (
        "_captaincy_appearance_for_run"
        in text
    ),

    "appearance wired": (
        text.count(
            "appearance_by_player_gameweek="
        )
        >= 2
    ),

    "captaincy ON": (
        text.count(
            "captaincy_weight=1.0"
        )
        >= 2
    ),

    "no captaincy OFF": (
        "captaincy_weight=0.0"
        not in text
    ),
}


for key, value in checks.items():

    print(
        key,
        "PASS"
        if value
        else "FAIL"
    )


assert all(
    checks.values()
)

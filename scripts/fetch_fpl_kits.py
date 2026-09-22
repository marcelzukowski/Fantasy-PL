from __future__ import annotations

import hashlib
import json
import struct
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.cwd()

STATE_PATH = (
    ROOT
    / "data"
    / "user"
    / "squad_state.json"
)

BOOTSTRAP_URL = (
    "https://fantasy.premierleague.com/"
    "api/bootstrap-static/"
)

KIT_BASE_URL = (
    "https://fantasy.premierleague.com/"
    "dist/img/shirts/standard/"
)

STAGE = (
    ROOT
    / "scratch"
    / "assets"
    / "assets001b_permanent_kit_cache"
)

STAGE.mkdir(
    parents=True,
    exist_ok=True,
)


def season_name() -> str:

    if STATE_PATH.exists():

        state = json.loads(
            STATE_PATH.read_text(
                encoding="utf-8-sig"
            )
        )

        season = str(
            state.get(
                "season",
                "2026/27",
            )
        )

        return season.replace(
            "/",
            "-",
        )


    return "2026-27"


def http_bytes(
    url: str,
) -> tuple[bytes, str | None]:

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/153.0 Safari/537.36"
            ),
            "Referer": (
                "https://fantasy.premierleague.com/"
            ),
        },
    )


    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as response:

        return (
            response.read(),
            response.headers.get(
                "Content-Type"
            ),
        )


def fetch_bootstrap() -> dict:

    req = urllib.request.Request(
        BOOTSTRAP_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "FPLControlCenter/kit-cache"
            ),
        },
    )


    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as response:

        return json.load(
            response
        )


def png_dimensions(
    data: bytes,
) -> tuple[int, int]:

    if not data.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):

        raise ValueError(
            "not PNG"
        )


    if len(data) < 24:

        raise ValueError(
            "PNG too short"
        )


    width = struct.unpack(
        ">I",
        data[
            16:20
        ],
    )[0]


    height = struct.unpack(
        ">I",
        data[
            20:24
        ],
    )[0]


    return (
        width,
        height,
    )


def digest(
    data: bytes,
) -> str:

    return hashlib.sha256(
        data
    ).hexdigest()


def download_one(
    team: dict,
    output_dir: Path,
) -> dict:

    team_id = int(
        team[
            "id"
        ]
    )

    team_code = int(
        team[
            "code"
        ]
    )


    last_error = None


    for size in (
        220,
        110,
        66,
    ):

        source_file = (
            f"shirt_"
            f"{team_code}"
            f"-{size}.png"
        )

        url = (
            KIT_BASE_URL
            + source_file
        )


        try:

            data, content_type = (
                http_bytes(
                    url
                )
            )


            width, height = (
                png_dimensions(
                    data
                )
            )


            if len(data) < 500:

                raise ValueError(
                    "unexpectedly small image"
                )


            filename = (
                f"team_{team_id}.png"
            )

            destination = (
                output_dir
                / filename
            )


            destination.write_bytes(
                data
            )


            return {
                "team_id": team_id,
                "team_code": team_code,
                "name": str(
                    team[
                        "name"
                    ]
                ),
                "short_name": str(
                    team[
                        "short_name"
                    ]
                ),
                "file": filename,
                "source_file": source_file,
                "source_url": url,
                "source_size": size,
                "content_type": content_type,
                "width": width,
                "height": height,
                "bytes": len(
                    data
                ),
                "sha256": digest(
                    data
                ),
            }


        except Exception as exc:

            last_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )


    raise RuntimeError(
        (
            f"Unable to fetch {team['name']}: "
            f"{last_error}"
        )
    )


season = season_name()

kit_dir = (
    ROOT
    / "desktop_app"
    / "assets"
    / "kits"
    / season
)

kit_dir.mkdir(
    parents=True,
    exist_ok=True,
)


bootstrap = fetch_bootstrap()

teams = bootstrap.get(
    "teams",
    []
)


print()
print("=" * 76)
print("ASSETS-001B PERMANENT FPL KIT CACHE")
print("=" * 76)

print(
    "season:",
    season,
)

print(
    "teams:",
    len(
        teams
    ),
)


if len(
    teams
) != 20:

    raise SystemExit(
        f"Expected 20 teams, got {len(teams)}"
    )


records = []


for team in sorted(
    teams,
    key=lambda row:
        int(
            row[
                "id"
            ]
        ),
):

    record = download_one(
        team,
        kit_dir,
    )

    records.append(
        record
    )


    print(
        "PASS | "
        f"{record['short_name']:>3} | "
        f"id={record['team_id']:>2} | "
        f"code={record['team_code']:>3} | "
        f"{record['width']}x"
        f"{record['height']} | "
        f"{record['file']}"
    )


manifest = {
    "schema_version": 1,
    "season": season,
    "generated_at_utc": (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    ),
    "source": (
        "Official Fantasy Premier League "
        "static shirt assets"
    ),
    "kit_base_url": KIT_BASE_URL,
    "preferred_source_size": 220,
    "team_count": len(
        records
    ),
    "teams": {
        str(
            row[
                "team_id"
            ]
        ): row
        for row
        in records
    },
    "team_code_to_id": {
        str(
            row[
                "team_code"
            ]
        ): row[
            "team_id"
        ]
        for row
        in records
    },
}


manifest_path = (
    kit_dir
    / "kit_manifest.json"
)


manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


# ============================================================
# VALIDATE CACHE
# ============================================================

problems = []


for row in records:

    file_path = (
        kit_dir
        / row[
            "file"
        ]
    )


    if not file_path.exists():

        problems.append(
            (
                row[
                    "short_name"
                ],
                "missing file",
            )
        )

        continue


    data = file_path.read_bytes()


    try:

        width, height = (
            png_dimensions(
                data
            )
        )

    except Exception as exc:

        problems.append(
            (
                row[
                    "short_name"
                ],
                str(
                    exc
                ),
            )
        )

        continue


    if digest(
        data
    ) != row[
        "sha256"
    ]:

        problems.append(
            (
                row[
                    "short_name"
                ],
                "SHA mismatch",
            )
        )


    if (
        width
        != row[
            "width"
        ]
        or height
        != row[
            "height"
        ]
    ):

        problems.append(
            (
                row[
                    "short_name"
                ],
                "dimension mismatch",
            )
        )


print()
print("=" * 76)
print("VALIDATION")
print("=" * 76)

print(
    "kits downloaded:",
    len(
        records
    ),
)

print(
    "kits valid:",
    (
        len(
            records
        )
        - len(
            problems
        )
    ),
)

print(
    "problems:",
    len(
        problems
    ),
)

print(
    "manifest:",
    manifest_path,
)


if problems:

    for team, problem in problems:

        print(
            "FAIL |",
            team,
            "|",
            problem,
        )


    raise SystemExit(
        1
    )


# ============================================================
# CREATE REUSABLE SCRIPT
# ============================================================

script_path = (
    ROOT
    / "scripts"
    / "fetch_fpl_kits.py"
)


script_path.write_text(
    Path(
        __file__
    ).read_text(
        encoding="utf-8"
    ),
    encoding="utf-8",
)


print()
print(
    "reusable script:",
    script_path,
)


# ============================================================
# UPDATE AGENTS.MD
# ============================================================

agents = (
    ROOT
    / "AGENTS.md"
)


if agents.exists():

    text = agents.read_text(
        encoding="utf-8-sig"
    )

else:

    text = "# AGENTS.md\n"


entry = """
## 2026-09-14 — ASSETS-001B — Permanent FPL kit cache

Completed:
- confirmed official FPL kit pattern:
  `shirt_<team.code>-<size>.png`,
- confirmed sizes 66, 110 and 220,
- downloaded all 20 current team kits,
- preferred source size is PNG 220,
- stored local assets under:
  `desktop_app/assets/kits/2026-27/`,
- local filename contract:
  `team_<team_id>.png`,
- created `kit_manifest.json`,
- manifest maps FPL team ID and team code,
- SHA256 and image metadata stored per kit,
- created reusable refresh script:
  `scripts/fetch_fpl_kits.py`.

Important:
- GUI should use local cached kits,
  not download them on every launch,
- player -> kit mapping uses canonical FPL `team_id`,
- source `team.code` is retained for provenance.

Next:
- integrate cached kits into player cards,
- show Current XI plus 4-player bench,
- enlarge MY SQUAD rows,
- add pick-quality metrics,
- add next-3-GW score boxes 0–100,
- color scores red -> yellow -> green.
"""


if (
    "ASSETS-001B — Permanent FPL kit cache"
    not in text
):

    text = (
        text.rstrip()
        + "\n\n"
        + entry.strip()
        + "\n"
    )


agents.write_text(
    text,
    encoding="utf-8",
)


print(
    "AGENTS.md: UPDATED"
)


# ============================================================
# FINAL SUMMARY
# ============================================================

print()
print("=" * 76)
print("RESULT")
print("=" * 76)

print(
    "KIT CACHE: FULL PASS"
)

print(
    "manifest teams:",
    len(
        manifest[
            "teams"
        ]
    ),
)

print(
    "PNG files:",
    len(
        list(
            kit_dir.glob(
                "team_*.png"
            )
        )
    ),
)

print(
    "kit dir:",
    kit_dir,
)

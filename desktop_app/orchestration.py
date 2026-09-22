from __future__ import annotations

from pathlib import Path
import json


class DesktopEngineError(
    RuntimeError
):
    pass


def resolve_engine_python(
    root: Path,
) -> Path:

    root = Path(
        root
    ).resolve()


    candidates = (
        root
        / ".venv"
        / "Scripts"
        / "python.exe",

        root
        / ".venv"
        / "bin"
        / "python",
    )


    for candidate in candidates:

        if candidate.exists():

            return candidate


    raise DesktopEngineError(
        "Project Python environment "
        "was not found under .venv."
    )


def projection_arguments(
    *,
    season: str,
    gameweek: int,
    simulation_count: int,
    seed: int,
) -> list[str]:

    season = str(
        season
    ).strip()


    if not season:

        raise DesktopEngineError(
            "Season cannot be empty."
        )


    gameweek = int(
        gameweek
    )

    simulation_count = int(
        simulation_count
    )

    seed = int(
        seed
    )


    if not (
        1
        <= gameweek
        <= 38
    ):

        raise DesktopEngineError(
            "Gameweek must be between "
            "1 and 38."
        )


    if simulation_count < 1:

        raise DesktopEngineError(
            "Simulation count must "
            "be positive."
        )


    if seed < 0:

        raise DesktopEngineError(
            "Seed must be non-negative."
        )


    return [
        "-m",
        "fpl_engine",

        "predict-current",

        "--season",
        season,

        "--gameweek",
        str(
            gameweek
        ),

        "--simulation-count",
        str(
            simulation_count
        ),

        "--seed",
        str(
            seed
        ),
    ]


def _run_matches_gameweek(
    run_dir: Path,
    gameweek: int | None,
) -> bool:

    if gameweek is None:

        return True


    context = (
        run_dir
        / "prediction_context.json"
    )


    if not context.exists():

        return False


    try:

        payload = json.loads(
            context.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):

        return False


    return (
        int(
            payload.get(
                "target_gameweek",
                -1,
            )
        )
        == int(
            gameweek
        )
    )


def latest_prediction_run(
    root: Path,
    season: str,
    *,
    gameweek: int | None = None,
) -> Path | None:

    root = Path(
        root
    ).resolve()


    base = (
        root
        / "data"
        / "processed"
        / "predictions"
        / str(
            season
        ).replace(
            "/",
            "-",
        )
    )


    if not base.exists():

        return None


    candidates = []


    for projections in base.glob(
        "*/player_projections.json"
    ):

        run_dir = (
            projections.parent
        )


        if not (
            run_dir
            / "run_manifest.json"
        ).exists():

            continue


        if not _run_matches_gameweek(
            run_dir,
            gameweek,
        ):

            continue


        candidates.append(
            run_dir
        )


    if not candidates:

        return None


    return max(
        candidates,
        key=lambda path: (
            (
                path
                / "player_projections.json"
            )
            .stat()
            .st_mtime
        ),
    )


def projection_run_summary(
    run_dir: Path,
) -> dict:

    run_dir = Path(
        run_dir
    )


    required = (
        "current_players.json",
        "fixture_horizon.json",
        "minutes.json",
        "player_projections.json",
        "run_manifest.json",
    )


    missing = [
        name
        for name in required
        if not (
            run_dir
            / name
        ).exists()
    ]


    if missing:

        raise DesktopEngineError(
            "Projection run is incomplete: "
            + ", ".join(
                missing
            )
        )


    context_path = (
        run_dir
        / "prediction_context.json"
    )


    context = {}


    if context_path.exists():

        try:

            context = json.loads(
                context_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            context = {}


    return {
        "run_directory":
            str(
                run_dir
            ),

        "season":
            context.get(
                "target_season"
            ),

        "gameweek":
            context.get(
                "target_gameweek"
            ),

        "player_projections":
            str(
                run_dir
                / "player_projections.json"
            ),

        "minutes":
            str(
                run_dir
                / "minutes.json"
            ),

        "manifest":
            str(
                run_dir
                / "run_manifest.json"
            ),

        "report":
            str(
                run_dir
                / "current_report.md"
            ),
    }

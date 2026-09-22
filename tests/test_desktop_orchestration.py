import json

import pytest

from desktop_app.orchestration import (
    DesktopEngineError,
    latest_prediction_run,
    projection_arguments,
    projection_run_summary,
    resolve_engine_python,
)


def test_projection_arguments():

    result = projection_arguments(
        season="2026/27",
        gameweek=5,
        simulation_count=256,
        seed=42,
    )


    assert result == [
        "-m",
        "fpl_engine",
        "predict-current",
        "--season",
        "2026/27",
        "--gameweek",
        "5",
        "--simulation-count",
        "256",
        "--seed",
        "42",
    ]


def test_projection_arguments_reject_invalid():

    with pytest.raises(
        DesktopEngineError,
    ):

        projection_arguments(
            season="2026/27",
            gameweek=0,
            simulation_count=256,
            seed=42,
        )


def test_resolve_engine_python(
    tmp_path,
):

    python = (
        tmp_path
        / ".venv"
        / "Scripts"
        / "python.exe"
    )


    python.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    python.write_bytes(
        b"fake"
    )


    assert (
        resolve_engine_python(
            tmp_path
        )
        == python
    )


def test_latest_prediction_run(
    tmp_path,
):

    base = (
        tmp_path
        / "data"
        / "processed"
        / "predictions"
        / "2026-27"
    )


    older = (
        base
        / "run_old"
    )

    newer = (
        base
        / "run_new"
    )


    for path, gw in (
        (
            older,
            4,
        ),
        (
            newer,
            5,
        ),
    ):

        path.mkdir(
            parents=True
        )


        (
            path
            / "player_projections.json"
        ).write_text(
            "[]",
            encoding="utf-8",
        )


        (
            path
            / "run_manifest.json"
        ).write_text(
            "{}",
            encoding="utf-8",
        )


        (
            path
            / "prediction_context.json"
        ).write_text(
            json.dumps({
                "target_season":
                    "2026/27",

                "target_gameweek":
                    gw,
            }),
            encoding="utf-8",
        )


    assert (
        latest_prediction_run(
            tmp_path,
            "2026/27",
            gameweek=5,
        )
        == newer
    )


def test_projection_run_summary(
    tmp_path,
):

    run = (
        tmp_path
        / "run"
    )

    run.mkdir()


    for name in (
        "current_players.json",
        "fixture_horizon.json",
        "minutes.json",
        "player_projections.json",
        "run_manifest.json",
    ):

        (
            run
            / name
        ).write_text(
            "[]"
            if name
            != "run_manifest.json"
            else "{}",
            encoding="utf-8",
        )


    (
        run
        / "prediction_context.json"
    ).write_text(
        json.dumps({
            "target_season":
                "2026/27",

            "target_gameweek":
                5,
        }),
        encoding="utf-8",
    )


    summary = (
        projection_run_summary(
            run
        )
    )


    assert (
        summary[
            "gameweek"
        ]
        == 5
    )

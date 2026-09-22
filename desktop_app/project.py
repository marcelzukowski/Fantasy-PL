from __future__ import annotations

from pathlib import Path
import os
import sys


class DesktopProjectError(
    RuntimeError
):
    pass


def _candidate_roots():

    explicit = os.environ.get(
        "FPL_ENGINE_ROOT"
    )


    if explicit:

        yield Path(
            explicit
        ).resolve()


    yield Path.cwd().resolve()


    if getattr(
        sys,
        "frozen",
        False,
    ):

        executable = Path(
            sys.executable
        ).resolve()


        yield executable.parent

        yield executable.parent.parent


    module_path = Path(
        __file__
    ).resolve()


    for parent in (
        module_path.parent,
        *module_path.parents,
    ):

        yield parent


def resolve_project_root() -> Path:

    seen = set()


    for candidate in _candidate_roots():

        candidate = candidate.resolve()


        if candidate in seen:

            continue


        seen.add(
            candidate
        )


        if (
            candidate
            / "src"
            / "fpl_engine"
        ).exists():

            return candidate


    raise DesktopProjectError(
        "Could not locate FPL Prediction "
        "Engine project root."
    )

from __future__ import annotations

from pathlib import Path


path = Path(
    "src/fpl_engine/current.py"
)

text = path.read_text(
    encoding="utf-8"
)


if (
    "HurdleTimeDecayMinutesModel"
    in text
):
    raise RuntimeError(
        "current.py already appears to contain "
        "Minutes V2 wiring; stopping to avoid "
        "double patching"
    )


# ============================================================
# A. IMPORT V2 MINUTES MODEL
# ============================================================

old = (
    "from fpl_engine.models.minutes import "
    "MinutesContext, MinutesFeatureSignal, MinutesModel\n"
)

new = (
    "from fpl_engine.models.minutes import "
    "MinutesContext, MinutesFeatureSignal, MinutesModel\n"
    "from fpl_engine.models.minutes.v2 import "
    "HurdleTimeDecayMinutesModel\n"
)

if old not in text:
    raise RuntimeError(
        "Minutes import marker not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# B. MANIFEST LOADER: V2 PREFERRED, V1 FALLBACK
# ============================================================

old = '''def _load_active_model_manifest(root: Path, season: str) -> Mapping[str, object]:
    path = root / "config" / "v1_champions.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CurrentInputError("The V1 champion manifest is unavailable or invalid") from exc
'''

new = '''def _load_active_model_manifest(root: Path, season: str) -> Mapping[str, object]:
    v2_path = root / "config" / "v2_champions.yaml"
    v1_path = root / "config" / "v1_champions.yaml"
    path = v2_path if v2_path.exists() else v1_path
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CurrentInputError("The champion manifest is unavailable or invalid") from exc
'''

if old not in text:
    raise RuntimeError(
        "manifest loader header not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# C. MANIFEST VALIDATION: ALLOW V1 OR V2 MINUTES
# ============================================================

old = '''    fixed = {
        "team_strength": "dixon_coles_v1_hl60_xg",
        "minutes": "minutes_hurdle_v1",
        "simulation": FixtureSimulator.VERSION,
        "projection": ProjectionBuilder.VERSION,
    }
'''

new = '''    fixed = {
        "team_strength": "dixon_coles_v1_hl60_xg",
        "simulation": FixtureSimulator.VERSION,
        "projection": ProjectionBuilder.VERSION,
    }
'''

if old not in text:
    raise RuntimeError(
        "fixed manifest block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


marker = '''    if active.get("player_talent") not in {
'''

addition = '''    if active.get("minutes") not in {
        "minutes_hurdle_v1",
        "minutes_hurdle_v2",
    }:
        mismatches["minutes"] = active.get("minutes")

'''

if marker not in text:
    raise RuntimeError(
        "Minutes validation insertion "
        "marker not found"
    )

text = text.replace(
    marker,
    addition + marker,
    1,
)


# ============================================================
# D. RUNTIME STACK ACTUALLY OBEYS MANIFEST
# ============================================================

old = '''    active = manifest["active"]
    talent = (
        PlayerTalentV2() if active["player_talent"] == "player_talent_reliability_v2"
        else PlayerTalentModel()
    )
    events = active["event_models"]
    event_model = EventModelsV2() if events["assists"] == "coherent_assists_v2" else EventModels()
    return TeamStrengthModel(), MinutesModel(), talent, event_model
'''

new = '''    active = manifest["active"]

    minutes = (
        HurdleTimeDecayMinutesModel()
        if active["minutes"] == "minutes_hurdle_v2"
        else MinutesModel()
    )

    talent = (
        PlayerTalentV2() if active["player_talent"] == "player_talent_reliability_v2"
        else PlayerTalentModel()
    )

    events = active["event_models"]
    event_model = EventModelsV2() if events["assists"] == "coherent_assists_v2" else EventModels()

    return TeamStrengthModel(), minutes, talent, event_model
'''

if old not in text:
    raise RuntimeError(
        "runtime model stack block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# E. VERSION-AWARE CALIBRATION PATH
# ============================================================

marker = '''def _persist_current_source_records(
'''

helper = '''def _minutes_calibration_path(
    root: Path,
    training_season: str,
    minutes_model_version: str,
) -> Path:
    if minutes_model_version == "minutes_hurdle_v1":
        filename = (
            f"minutes_calibration_{training_season}.json"
        )
    elif minutes_model_version == "minutes_hurdle_v2":
        filename = (
            f"minutes_calibration_v21_{training_season}.json"
        )
    else:
        raise CurrentInputError(
            "Unsupported Minutes model version: "
            f"{minutes_model_version}"
        )

    return (
        root
        / "data"
        / "processed"
        / "models"
        / "minutes"
        / filename
    )


'''

if marker not in text:
    raise RuntimeError(
        "calibration resolver insertion "
        "marker not found"
    )

text = text.replace(
    marker,
    helper + marker,
    1,
)


# ============================================================
# F. CURRENT PIPELINE USES MATCHING CALIBRATOR
# ============================================================

old = '''        minutes_calibration_path = (
            self.project_root
            / "data"
            / "processed"
            / "models"
            / "minutes"
            / f"minutes_calibration_{minutes_calibration_season}.json"
        )
'''

new = '''        minutes_model_version = (
            champion_manifest["active"]["minutes"]
        )

        minutes_calibration_path = (
            _minutes_calibration_path(
                self.project_root,
                minutes_calibration_season,
                minutes_model_version,
            )
        )
'''

if old not in text:
    raise RuntimeError(
        "calibration path block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# G. RUN MANIFEST RECORDS REAL ACTIVE MODEL
# ============================================================

old = '''                "champion_status": champion_manifest.get("status", "KEEP_TESTING"),
                "active_v1": champion_manifest["active"],
                "model_artifacts": {
                    "minutes_calibration": {
                        "artifact_version": "minutes_calibration_v1",
                        "training_season": minutes_calibration_season,
'''

new = '''                "champion_status": champion_manifest.get("status", "KEEP_TESTING"),
                "active_models": champion_manifest["active"],
                # Backward-compatible alias retained for old readers.
                "active_v1": champion_manifest["active"],
                "model_artifacts": {
                    "minutes_calibration": {
                        "artifact_version": "minutes_calibration_v1",
                        "model_version": minutes_model_version,
                        "training_season": minutes_calibration_season,
'''

if old not in text:
    raise RuntimeError(
        "run manifest metadata block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


path.write_text(
    text,
    encoding="utf-8"
)

print(
    "current.py patched successfully"
)

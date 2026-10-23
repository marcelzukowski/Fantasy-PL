from copy import deepcopy
import json

import pytest
from desktop_app.manual_scenario_store import ScenarioStore


def test_save_rename_reload_delete_and_duplicate_context(tmp_path):
    store = ScenarioStore(tmp_path / "scenarios.json")
    first = store.save("Plan", [], [], "ctx", "input", None)
    same = store.save("Renamed", [], [], "ctx", "input", None)
    assert first["id"] == same["id"] and len(store.load()) == 1
    store.rename(first["id"], "Another name")
    assert ScenarioStore(store.path).load()[0]["name"] == "Another name"
    other = store.save("New context", [], [], "ctx2", "input2", None)
    assert other["id"] != first["id"] and len(store.load()) == 2
    store.delete(first["id"])
    assert len(store.load()) == 1


def test_corrupt_file_is_not_overwritten(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text("{broken")
    with pytest.raises(ValueError):
        ScenarioStore(path).save("Plan", [], [], "ctx", "input", None)
    assert path.read_text() == "{broken"


def test_result_identity_must_match_and_no_duplicate_transfer_ids(tmp_path):
    store = ScenarioStore(tmp_path / "scenarios.json")
    with pytest.raises(ValueError):
        store.save("Plan", ["a", "a"], ["b", "c"], "ctx", "input", None)
    with pytest.raises(ValueError):
        store.save("Plan", [], [], "ctx", "input", {"context_id": "stale"})
    assert not store.path.exists()


@pytest.fixture(scope="module")
def native_result():
    from desktop_app.manual_scenario_engine import ManualScenarioEvaluator
    from tests.test_manual_scenario_engine import _shared

    return ManualScenarioEvaluator(_shared()).evaluate([], [])


def test_full_native_result_roundtrip(tmp_path, native_result):
    store = ScenarioStore(tmp_path / "scenarios.json")
    store.save("Native", [], [], "ctx", native_result["input_sha256"], native_result)
    assert store.load()[0]["result"] == native_result


@pytest.mark.parametrize(
    "damage",
    [
        "objective",
        "partial",
        "delta",
        "captain",
        "first_step",
        "nan",
        "bool",
        "path_total",
        "terminal",
        "baseline",
        "lineup",
        "future_roster",
        "input",
    ],
)
def test_invalid_native_result_is_rejected_and_selections_recoverable(
    tmp_path, native_result, damage
):
    result = deepcopy(native_result)
    scenario = result["scenario"]
    if damage == "objective":
        scenario["objective"] += 100
    elif damage == "partial":
        del scenario["path"]
    elif damage == "delta":
        scenario["delta_hold"] += 1
    elif damage == "captain":
        scenario["captain"] = "not-in-xi"
    elif damage == "first_step":
        scenario["path"][0]["transfers_out"] = ["p0"]
        scenario["path"][0]["transfers_in"] = ["new0"]
    elif damage == "nan":
        scenario["path"][1]["lineup_points"] = float("nan")
    elif damage == "bool":
        scenario["bank_after"] = True
    elif damage == "path_total":
        scenario["path_points"] += 1
    elif damage == "terminal":
        scenario["terminal_ft_value"] += 1
    elif damage == "baseline":
        result["hold"]["objective"] += 1
    elif damage == "lineup":
        scenario["path"][1]["starting_xi"][1] = scenario["path"][1]["starting_xi"][0]
    elif damage == "future_roster":
        scenario["path"][1]["bench_order"][0] = "unknown"
    elif damage == "input":
        result["input_sha256"] = "other"
    store = ScenarioStore(tmp_path / "scenarios.json")
    with pytest.raises(ValueError):
        store.save("Bad", [], [], "ctx", native_result["input_sha256"], result)
    row = store.save("Recover", [], [], "ctx", native_result["input_sha256"], None)
    row["result"] = result
    row["status"] = "evaluated"
    original = json.dumps({"schema_version": 1, "scenarios": [row]})
    store.path.write_text(original, encoding="utf-8")
    loaded = store.load()[0]
    assert loaded["result"] is None
    assert loaded["status"] == "invalid"
    assert "re-evaluat" in loaded["result_error"].lower()
    assert loaded["transfers_out"] == loaded["transfers_in"] == []
    assert store.path.read_text(encoding="utf-8") == original


def test_renaming_preserves_original_invalid_payload(tmp_path, native_result):
    store = ScenarioStore(tmp_path / "scenarios.json")
    row = store.save("Recover", [], [], "ctx", native_result["input_sha256"], native_result)
    row["result"] = deepcopy(row["result"])
    row["result"]["scenario"]["objective"] += 100
    store.path.write_text(json.dumps({"schema_version": 1, "scenarios": [row]}), encoding="utf-8")
    store.rename(row["id"], "New name")
    raw = json.loads(store.path.read_text(encoding="utf-8"))["scenarios"][0]
    assert raw["result"] == row["result"]
    assert raw["name"] == "New name"
    assert store.load()[0]["result"] is None


@pytest.mark.parametrize("root", [[], None, {"schema_version": True, "scenarios": []}])
def test_malformed_root_is_preserved(tmp_path, root):
    store = ScenarioStore(tmp_path / "scenarios.json")
    original = json.dumps(root)
    store.path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        store.save("Plan", [], [], "ctx", "input", None)
    assert store.path.read_text(encoding="utf-8") == original

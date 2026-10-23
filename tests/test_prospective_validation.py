import json
import importlib
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

pv = importlib.import_module("fpl_engine.validation.prospective")


def _players(ids):
    positions = [
        "GK",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "MID",
        "MID",
        "MID",
        "MID",
        "FWD",
        "FWD",
        "GK",
        "DEF",
        "MID",
        "FWD",
    ]
    return {pid: {"provider_id": str(i), "position": positions[i]} for i, pid in enumerate(ids)}


def test_tied_spearman_and_matched_error_metrics():
    rows = [{"xp": 1, "points": 1}, {"xp": 1, "points": 3}, {"xp": 4, "points": 4}]
    metrics = pv._metrics(rows, "xp", "points")
    assert metrics["n"] == 3 and metrics["mae"] == pytest.approx(2 / 3)
    assert metrics["rmse"] == pytest.approx((4 / 3) ** 0.5) and metrics["bias"] == pytest.approx(
        -2 / 3
    )
    assert pv._spearman(rows) == pytest.approx(0.8660254037844386)
    assert pv._spearman([{"xp": 1, "points": 2}, {"xp": 1, "points": 3}]) is None


def test_v22_identity_rejects_mixed_simulator_bundle():
    version = pv.V22_SIMULATOR
    manifest = {"simulation": {"simulator_version": version}}
    base = {"pipeline": {"simulator_version": version}, "projections": []}
    assert not pv._is_v22_bundle(base, manifest)
    assert pv._is_v22_bundle({**base, "projections": [{"simulator_versions": [version]}]}, manifest)
    assert not pv._is_v22_bundle(
        {
            **base,
            "projections": [{"simulator_versions": [version, "legacy"]}],
        },
        manifest,
    )


def test_markdown_reports_cohort_baselines_and_paired_policy_gain():
    metric = {"n": 1, "mae": 1.0, "rmse": 1.0, "bias": 0.0}
    baseline = {"n": 1, "v22": metric, "baseline": metric}
    baseline_keys = ("previous_gw", "recent3", "minutes_aware")
    group_keys = (
        "all_players",
        "predicted_starters",
        "high_xp",
        "frozen_transfer_candidates",
        "saved_xi_candidates",
    )
    score = {key: metric for key in group_keys}
    score.update(
        {
            "minutes": metric,
            "by_position": {key: metric for key in ("GK", "DEF", "MID", "FWD")},
            "minutes_by_position": {key: metric for key in ("GK", "DEF", "MID", "FWD")},
            "by_predicted_minutes": {"[60,80)": metric},
            "minutes_by_predicted_minutes": {"[60,80)": metric},
            "by_gameweek": {"6": {"points": metric, "minutes": metric}},
            "baseline_by_group": {
                group: {key: baseline for key in baseline_keys} for group in group_keys
            },
            "saved_v3_vs_hold_paired": {
                "by_gameweek": {
                    "6": {
                        "v3_points": 24.0,
                        "hold_points": 20.0,
                        "v3_minus_hold_points": 4.0,
                    }
                },
                "n_gameweeks": 1,
                "mean_v3_minus_hold_points": 4.0,
                "total_v3_minus_hold_points": 4.0,
            },
        }
    )
    rendered = pv._render_markdown(
        {
            "season": "2026/27",
            "selected_gameweeks": [6],
            "scorecard": score,
            "primary_archives": [],
            "exclusions": [],
            "decision_scores": [],
        }
    )
    assert "| All players | Previous completed GW points | 1 |" in rendered
    assert "| 6 | 1 | 1.0 | 1.0 |" in rendered
    assert "| 6 | 24.0 | 20.0 | 4.0 |" in rendered
    assert "current code" in rendered


def test_raw_payload_hash_mismatch_is_an_explicit_exclusion(tmp_path):
    snapshot = tmp_path / "data/raw/official_fpl_api/event_live/2026-10-01/s1"
    snapshot.mkdir(parents=True)
    (snapshot / "snapshot.metadata.json").write_text(
        json.dumps({"checksum": "0" * 64}), encoding="utf-8"
    )
    (snapshot / "payload.bin").write_text("{}", encoding="utf-8")
    failures = []
    assert pv._snapshots(tmp_path, "event_live", {}, failures) == []
    assert len(failures) == 1 and "checksum mismatch" in failures[0]["reason"]


def test_pending_or_unchecked_outcome_is_not_scored():
    now = "2026-10-20T12:00:00Z"
    bootstrap = [
        (
            {"source_record_id": "8", "retrieved_at": now, "snapshot_id": "b"},
            {"events": [{"id": 8, "finished": True, "data_checked": False}]},
            Path("bootstrap"),
        )
    ]
    live = [
        (
            {"source_record_id": "8", "retrieved_at": now, "source_provider": "official_fpl_api"},
            {"elements": [{"id": 1, "stats": {"total_points": 0, "minutes": 0}}]},
            Path("live"),
        )
    ]
    assert pv._official_outcomes(live, bootstrap, 8, now) is None


def test_final_outcomes_accept_later_same_season_snapshot_but_reject_stale_in_play(tmp_path):
    deadline = "2026-10-10T10:00:00Z"
    checked_at = "2026-10-10T18:00:00Z"
    events = [
        {"id": 1, "deadline_time": "2026-08-15T10:00:00Z", "finished": True, "data_checked": True},
        {"id": 6, "deadline_time": deadline, "finished": True, "data_checked": True},
        {
            "id": 38,
            "deadline_time": "2027-05-23T10:00:00Z",
            "finished": False,
            "data_checked": False,
        },
    ]
    bootstrap = [
        (
            {"retrieved_at": checked_at, "snapshot_id": "checked"},
            {"events": events},
            Path("bootstrap"),
        )
    ]
    stale = (
        {
            "source_record_id": "6",
            "retrieved_at": "2026-10-10T12:00:00Z",
            "source_provider": "official_fpl_api",
        },
        {"elements": [{"id": 1, "stats": {"total_points": 2, "minutes": 90}}]},
        Path("stale"),
    )
    later = (
        {
            "source_record_id": "6",
            "retrieved_at": "2026-10-23T12:00:00Z",
            "snapshot_id": "final",
            "source_provider": "official_fpl_api",
        },
        {"elements": [{"id": 1, "stats": {"total_points": 5, "minutes": 90}}]},
        Path("later"),
    )
    assert pv._official_outcomes([stale], bootstrap, 6, deadline) is None
    result = pv._official_outcomes([stale, later], bootstrap, 6, deadline)
    assert result is not None and result[1]["1"]["total_points"] == 5


def test_stale_hold_preview_is_unavailable(tmp_path):
    ids = [f"p{i}" for i in range(15)]
    hold = {
        "gw": 6,
        "action": "HOLD",
        "transfers_in": [],
        "transfers_out": [],
        "resulting_squad": ids,
        "starting_xi": ids[:11],
        "bench_order": ids[11:],
        "captain": ids[0],
        "vice_captain": ids[1],
        "hit_cost_points": 0,
    }
    report = {
        "context_id": "context",
        "policy_results": {
            "strategic_v3": {
                "current_action": {
                    "action": "HOLD",
                    "transfers_in": [],
                    "transfers_out": [],
                    "hit_cost_points": 0,
                },
                "path": [hold],
                "hold_now_counterfactual": {
                    "path": [{**hold, "resulting_squad": ids[:-1] + ["stale"]}]
                },
            }
        },
    }
    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps(report), encoding="utf-8")
    case = SimpleNamespace(
        decision_report=SimpleNamespace(path="decision.json"),
        context_id="context",
        planning_gameweek=6,
        planning_context=SimpleNamespace(player_ids=tuple(ids)),
    )
    players = _players(ids)
    outcomes = {str(i): {"total_points": 2, "minutes": 90} for i in range(15)}
    result = pv._decision_rows(tmp_path, case, outcomes, players)
    assert result[0]["status"] == "SCORED"
    assert result[1]["status"] == "UNAVAILABLE"
    assert "inconsistent" in result[1]["reason"]


def test_saved_decisions_use_real_archived_planning_context(tmp_path):
    archive_tests = runpy.run_path("tests/test_replay_archive.py")
    root, analysis_path, decision_path, _ = archive_tests["_root"](tmp_path)
    archive_path = archive_tests["archive_analysis"](root, analysis_path)
    case = pv.parse_archive_case(archive_path)
    ids = list(case.planning_context.player_ids)
    action = {
        "gw": case.planning_gameweek,
        "action": "HOLD",
        "transfers_out": [],
        "transfers_in": [],
        "resulting_squad": ids,
        "starting_xi": ids[:11],
        "bench_order": ids[11:],
        "captain": ids[0],
        "vice_captain": ids[1],
        "hit_cost_points": 0,
    }
    report = json.loads(decision_path.read_text(encoding="utf-8"))
    report["policy_results"]["strategic_v3"] = {
        "current_action": {
            "action": "HOLD",
            "transfers_out": [],
            "transfers_in": [],
            "hit_cost_points": 0,
        },
        "path": [action],
        "hold_now_counterfactual": {"path": [action]},
    }
    decision_path.write_text(json.dumps(report), encoding="utf-8")
    players = _players(ids)
    outcomes = {str(i): {"total_points": 2, "minutes": 90} for i in range(15)}
    scores = pv._decision_rows(root, case, outcomes, players)
    assert [row["status"] for row in scores] == ["SCORED", "SCORED"]
    assert scores[0]["points"] == pytest.approx(24)


def test_frozen_decision_scores_canonical_bench_and_vice_captain_when_captain_dnp(
    tmp_path,
):
    ids = [f"p{i}" for i in range(15)]
    action = {
        "gw": 6,
        "action": "HOLD",
        "transfers_in": [],
        "transfers_out": [],
        "resulting_squad": ids,
        "starting_xi": ids[:11],
        "bench_order": ids[11:],
        "captain": ids[0],
        "vice_captain": ids[1],
        "hit_cost_points": 0,
    }
    (tmp_path / "decision.json").write_text(
        json.dumps(
            {
                "context_id": "context",
                "policy_results": {
                    "strategic_v3": {
                        "current_action": {
                            "action": "HOLD",
                            "transfers_in": [],
                            "transfers_out": [],
                            "hit_cost_points": 0,
                        },
                        "path": [action],
                        "hold_now_counterfactual": {"path": [action]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    players = _players(ids)
    outcomes = {str(i): {"total_points": 2, "minutes": 90} for i in range(15)}
    outcomes["0"] = {"total_points": 0, "minutes": 0}
    outcomes["11"] = {"total_points": 3, "minutes": 90}
    case = SimpleNamespace(
        decision_report=SimpleNamespace(path="decision.json"),
        context_id="context",
        planning_gameweek=6,
        planning_context=SimpleNamespace(player_ids=tuple(ids)),
    )
    scores = pv._decision_rows(tmp_path, case, outcomes, players)
    assert [row["status"] for row in scores] == ["SCORED", "SCORED"]
    assert scores[0]["autosub_status"] == "CANONICAL_REALIZED_AUTOSUBS"
    # The GK DNP is replaced by the bench GK (3 points); the vice gets the captain bonus.
    assert scores[0]["points"] == pytest.approx(25)


@pytest.mark.parametrize("invalid_lineup", ["duplicate_xi", "captain_on_bench", "unsupported_chip"])
def test_invalid_saved_lineup_is_unavailable(tmp_path, invalid_lineup):
    ids = [f"p{i}" for i in range(15)]
    action = {
        "gw": 6,
        "action": "HOLD",
        "transfers_in": [],
        "transfers_out": [],
        "resulting_squad": ids,
        "starting_xi": ids[:11],
        "bench_order": ids[11:],
        "captain": ids[0],
        "vice_captain": ids[1],
        "hit_cost_points": 0,
    }
    if invalid_lineup == "duplicate_xi":
        action["starting_xi"][-1] = action["starting_xi"][0]
    elif invalid_lineup == "captain_on_bench":
        action["captain"] = ids[11]
    else:
        action["chip"] = "bench_boost"
    (tmp_path / "decision.json").write_text(
        json.dumps(
            {
                "context_id": "context",
                "policy_results": {
                    "strategic_v3": {
                        "current_action": {
                            "action": "HOLD",
                            "transfers_out": [],
                            "transfers_in": [],
                            "hit_cost_points": 0,
                        },
                        "path": [action],
                        "hold_now_counterfactual": {"path": [action]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    case = SimpleNamespace(
        decision_report=SimpleNamespace(path="decision.json"),
        context_id="context",
        planning_gameweek=6,
        planning_context=SimpleNamespace(player_ids=tuple(ids)),
    )
    players = _players(ids)
    outcomes = {str(i): {"total_points": 2, "minutes": 90} for i in range(15)}
    result = pv._decision_rows(tmp_path, case, outcomes, players)
    assert [row["status"] for row in result] == ["UNAVAILABLE", "UNAVAILABLE"]


def test_locked_archive_hash_change_fails_without_falling_back(tmp_path, monkeypatch):
    locked = tmp_path / "locked.json"
    alternative = tmp_path / "alternative.json"
    locked.write_text("changed", encoding="utf-8")
    alternative.write_text("valid candidate", encoding="utf-8")
    ledger = tmp_path / "locks.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "season": "2026/27",
                "gameweek": 6,
                "archive_path": "locked.json",
                "archive_sha256": "0" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    case = SimpleNamespace(season="2026/27", planning_gameweek=6)
    monkeypatch.setattr(pv, "discover_archives", lambda *_: (locked, alternative))
    monkeypatch.setattr(pv, "parse_archive_case", lambda _: case)
    with pytest.raises(pv.ProspectiveValidationError, match="Locked archive changed"):
        pv._select_archives(tmp_path, "2026/27", [6], [], ledger)


def test_primary_ledger_accepts_idempotent_repeated_entry_and_rejects_rewrite(tmp_path):
    ledger = tmp_path / "locks.jsonl"
    entry = {
        "season": "2026/27",
        "gameweek": 6,
        "archive_path": "case.json",
        "archive_sha256": "a" * 64,
    }
    line = json.dumps(entry, sort_keys=True)
    ledger.write_text(line + "\n" + line + "\n", encoding="utf-8")
    assert pv._read_ledger(ledger)["2026/27:6"] == entry
    changed = {**entry, "archive_sha256": "b" * 64}
    ledger.write_text(line + "\n" + json.dumps(changed) + "\n", encoding="utf-8")
    with pytest.raises(pv.ProspectiveValidationError, match="Conflicting primary lock"):
        pv._read_ledger(ledger)


def test_parallel_or_stale_ledger_lock_is_rejected(tmp_path):
    ledger = tmp_path / "locks.jsonl"
    (tmp_path / "locks.jsonl.lock").write_text("active", encoding="utf-8")
    with pytest.raises(pv.ProspectiveValidationError, match="Selection ledger is locked"):
        pv.evaluate(tmp_path, "2026/27", tmp_path / "report", ledger_path=ledger)

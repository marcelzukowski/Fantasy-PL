"""Offline, append-only prospective scoring for frozen V22 and saved V3 decisions.

Run with ``python -m fpl_engine.validation.prospective --help``. This module only
reads local archives and official public-data snapshots; it never executes a
projection, planner, provider request, or account operation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
from statistics import mean
from typing import Any, Mapping, Sequence

from fpl_engine.decision.autosubs import AutosubError, evaluate_autosub_lineup
from fpl_engine.validation.replay_archive import (
    ArchiveStatus,
    ReplayArchiveError,
    _utc,
    discover_archives,
    parse_archive_case,
    validate_archive_case,
)

SCHEMA = "prospective_validation_v1"
MIN_GWS_FOR_UNCERTAINTY = 20
STARTER_MINUTES = 60.0
V22_SIMULATOR = "fixture_simulator_v22_lineup_coherent_logit"


class ProspectiveValidationError(ValueError):
    """The frozen local evidence is inconsistent or incomplete."""


def _load(path: Path, inventory: dict[str, str] | None = None) -> Any:
    body = path.read_bytes()
    if inventory is not None:
        inventory[str(path.resolve()).replace("\\", "/")] = sha256(body).hexdigest()
    try:
        return json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProspectiveValidationError("Invalid JSON artifact.") from exc


def _json_snapshot(meta_path: Path, inventory: dict[str, str]) -> tuple[Mapping[str, Any], Any]:
    meta = _load(meta_path, inventory)
    payload_path = meta_path.parent / "payload.bin"
    body = payload_path.read_bytes()
    digest = sha256(body).hexdigest()
    inventory[str(payload_path.resolve()).replace("\\", "/")] = digest
    if digest != meta.get("checksum"):
        raise ProspectiveValidationError("Raw snapshot checksum mismatch.")
    try:
        payload = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProspectiveValidationError("Invalid raw snapshot JSON.") from exc
    return meta, payload


def _snapshots(
    root: Path, kind: str, inventory: dict[str, str], failures: list[dict[str, str]] | None = None
) -> list[tuple[Mapping[str, Any], Any, Path]]:
    base = root / "data" / "raw" / "official_fpl_api" / kind
    rows = []
    if base.exists():
        for path in sorted(base.glob("*/*/snapshot.metadata.json")):
            try:
                meta, payload = _json_snapshot(path, inventory)
                if kind == "event_live":
                    _event(meta)
                rows.append((meta, payload, path))
            except (OSError, ProspectiveValidationError) as exc:
                if failures is not None:
                    failures.append(
                        {
                            "source": str(path.relative_to(root)).replace("\\", "/"),
                            "reason": str(exc)
                            if isinstance(exc, ProspectiveValidationError)
                            else f"{type(exc).__name__}: unreadable",
                        }
                    )
    return rows


def _event(meta: Mapping[str, Any]) -> int:
    try:
        return int(meta["source_record_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProspectiveValidationError(
            "Official event snapshot has no numeric event ID."
        ) from exc


def _completion_at(
    bootstrap: Sequence[tuple[Mapping[str, Any], Any, Path]],
    gw: int,
    deadline: str,
    cutoff: datetime | None = None,
) -> datetime | None:
    matches = []
    target = _utc(deadline, "official event deadline")
    for meta, payload, _ in bootstrap:
        retrieved = _utc(meta["retrieved_at"], "bootstrap retrieved_at")
        if cutoff is not None and retrieved > cutoff:
            continue
        event = next((row for row in payload.get("events", ()) if row.get("id") == gw), None)
        if (
            event
            and _utc(event.get("deadline_time", ""), "official event deadline") == target
            and event.get("finished") is True
            and event.get("data_checked") is True
        ):
            matches.append(retrieved)
    return min(matches) if matches else None


def _official_deadline(
    bootstrap: Sequence[tuple[Mapping[str, Any], Any, Path]], gw: int, prediction: datetime
) -> tuple[str | None, str | None]:
    eligible = [
        (meta, payload)
        for meta, payload, _ in bootstrap
        if _utc(meta["retrieved_at"], "bootstrap retrieved_at") <= prediction
    ]
    if not eligible:
        return None, None
    meta, payload = max(
        eligible, key=lambda row: _utc(row[0]["retrieved_at"], "bootstrap retrieved_at")
    )
    event = next((row for row in payload.get("events", ()) if row.get("id") == gw), None)
    return (event.get("deadline_time"), str(meta.get("snapshot_id"))) if event else (None, None)


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_v22_bundle(raw: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    """Reject bundles whose declared run identity or individual rows mix simulators."""
    pipeline = raw.get("pipeline")
    simulation = manifest.get("simulation")
    projections = raw.get("projections")
    return (
        isinstance(pipeline, Mapping)
        and pipeline.get("simulator_version") == V22_SIMULATOR
        and isinstance(simulation, Mapping)
        and simulation.get("simulator_version") == V22_SIMULATOR
        and isinstance(projections, list)
        and bool(projections)
        and all(
            isinstance(row, Mapping) and row.get("simulator_versions") == [V22_SIMULATOR]
            for row in projections
        )
    )


def _walk_transfer_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key in ("transfers_in", "transfers_out"):
            ids = value.get(key)
            if isinstance(ids, list):
                found.update(str(pid) for pid in ids)
        for child in value.values():
            found.update(_walk_transfer_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_walk_transfer_ids(child))
    return found


def _read_ledger(path: Path) -> dict[str, Mapping[str, Any]]:
    if not path.exists():
        return {}
    locked: dict[str, Mapping[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            key = f"{row['season']}:{int(row['gameweek'])}"
            if key in locked and locked[key] != row:
                raise ProspectiveValidationError(
                    f"Conflicting primary lock entries for {key} at ledger line {line_number}."
                )
            locked[key] = row
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ProspectiveValidationError):
                raise
            raise ProspectiveValidationError(
                f"Malformed primary lock ledger line {line_number}."
            ) from exc
    return locked


def _select_archives(
    root: Path,
    season: str,
    gws: Sequence[int],
    bootstrap: Sequence[tuple[Mapping[str, Any], Any, Path]],
    ledger_path: Path,
) -> tuple[
    dict[int, tuple[Path, Any, Mapping[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]
]:
    locks = _read_ledger(ledger_path)
    selected: dict[int, tuple[Path, Any, Mapping[str, Any]]] = {}
    exclusions: list[dict[str, Any]] = []
    new_locks: list[dict[str, Any]] = []
    paths = discover_archives(root, season)
    by_gw: dict[int, list[Path]] = defaultdict(list)
    for path in paths:
        case = parse_archive_case(path)
        if case.planning_gameweek in gws:
            by_gw[case.planning_gameweek].append(path)
    for gw in gws:
        key = f"{season}:{gw}"
        candidates = by_gw.get(gw, [])
        eligible = []
        rejected: dict[Path, str] = {}
        for candidate in candidates:
            try:
                case = parse_archive_case(candidate)
                validation = validate_archive_case(root, candidate)
                reason = None
                if validation.status is not ArchiveStatus.PRE_DEADLINE_COMPLETE:
                    reason = "archive validation failed: " + "; ".join(validation.reasons)
                elif _utc(case.archive_created_at, "archive_created_at") >= _utc(
                    case.official_deadline, "official deadline"
                ):
                    reason = "archive was captured at/after deadline"
                else:
                    prediction = _utc(
                        case.planning_context.prediction_timestamp, "prediction timestamp"
                    )
                    deadline, deadline_snapshot = _official_deadline(bootstrap, gw, prediction)
                    if not deadline or _utc(deadline, "official deadline") != _utc(
                        case.official_deadline, "archive deadline"
                    ):
                        reason = "no matching official local bootstrap deadline observed by prediction time"
                    elif prediction >= _utc(deadline, "official deadline"):
                        reason = "prediction at/after official deadline"
                    elif (
                        not str(case.projection_bundle.path)
                        .replace("\\", "/")
                        .startswith("data/processed/predictions/")
                    ):
                        reason = "bundle is outside canonical prediction runs"
                    else:
                        bundle = root / case.projection_bundle.path
                        raw = _load(bundle)
                        manifest = _load(root / case.projection_manifest.path)
                        if raw.get("season") != season or not _is_v22_bundle(raw, manifest):
                            reason = "bundle season/simulator is not the requested production V22"
                        elif not manifest.get("artifacts"):
                            reason = "projection run has no artifact hash manifest"
                if reason:
                    rejected[candidate] = reason
                else:
                    eligible.append(
                        (
                            prediction,
                            _utc(case.archive_created_at, "archive_created_at"),
                            candidate,
                            case,
                            validation.to_dict(),
                            deadline_snapshot,
                        )
                    )
            except (
                OSError,
                ReplayArchiveError,
                ProspectiveValidationError,
                KeyError,
                TypeError,
            ) as exc:
                rejected[candidate] = f"invalid evidence: {exc}"
        if key in locks:
            lock = locks[key]
            path = (root / str(lock["archive_path"])).resolve()
            if not path.is_file() or _hash(path) != lock.get("archive_sha256"):
                raise ProspectiveValidationError(
                    f"Locked archive changed or disappeared for {key}: {path}"
                )
            try:
                case = parse_archive_case(path)
            except ReplayArchiveError as exc:
                raise ProspectiveValidationError(f"Locked archive is invalid for {key}.") from exc
            if (
                case.season.replace("/", "-") != season.replace("/", "-")
                or case.planning_gameweek != gw
            ):
                raise ProspectiveValidationError(f"Locked archive identity mismatch for {key}.")
            validation = validate_archive_case(root, path)
            if validation.status is not ArchiveStatus.PRE_DEADLINE_COMPLETE:
                raise ProspectiveValidationError(
                    f"Locked archive no longer validates for {key}: {validation.reasons}"
                )
            if _utc(case.archive_created_at, "archive_created_at") >= _utc(
                case.official_deadline, "official deadline"
            ):
                raise ProspectiveValidationError(
                    f"Locked archive was created after the deadline for {key}."
                )
            locked_candidate = next((row for row in eligible if row[2].resolve() == path), None)
            if locked_candidate is None:
                raise ProspectiveValidationError(
                    f"Locked archive is no longer an eligible primary for {key}."
                )
            selected[gw] = (path, case, validation.to_dict())
            for other, reason in rejected.items():
                exclusions.append(
                    {"gameweek": gw, "archive": str(other.relative_to(root)), "reason": reason}
                )
            for row in eligible:
                if row[2].resolve() != path:
                    exclusions.append(
                        {
                            "gameweek": gw,
                            "archive": str(row[2].relative_to(root)),
                            "reason": "another verified pre-deadline archive selected as primary",
                        }
                    )
            continue
        if not eligible:
            exclusions.extend(
                {"gameweek": gw, "archive": str(path.relative_to(root)), "reason": reason}
                for path, reason in rejected.items()
            )
            continue
        _, _, path, case, validation, _ = max(
            eligible, key=lambda row: (row[0], row[1], str(row[2]))
        )
        lock = {
            "season": season,
            "gameweek": gw,
            "archive_path": str(path.relative_to(root)).replace("\\", "/"),
            "archive_sha256": _hash(path),
            "projection_bundle_sha256": case.projection_bundle.sha256,
            "context_id": case.context_id,
        }
        selected[gw] = (path, case, validation)
        new_locks.append(lock)
        exclusions.extend(
            {"gameweek": gw, "archive": str(other.relative_to(root)), "reason": reason}
            for other, reason in rejected.items()
        )
        for row in eligible:
            if row[2].resolve() != path:
                exclusions.append(
                    {
                        "gameweek": gw,
                        "archive": str(row[2].relative_to(root)),
                        "reason": "another verified pre-deadline archive selected as primary",
                    }
                )
    return selected, exclusions, new_locks


def _official_outcomes(
    event_live: Sequence[tuple[Mapping[str, Any], Any, Path]],
    bootstrap: Sequence[tuple[Mapping[str, Any], Any, Path]],
    gw: int,
    expected_deadline: str,
) -> tuple[Mapping[str, Any], dict[str, Mapping[str, Any]], Mapping[str, Any]] | None:
    expected = _utc(expected_deadline, "archive official deadline")
    finals = [
        (meta, payload)
        for meta, payload, _ in bootstrap
        if any(
            row.get("id") == gw
            and row.get("deadline_time")
            and _utc(row["deadline_time"], "official event deadline") == expected
            for row in payload.get("events", ())
        )
    ]
    if not finals:
        return None
    final_meta, final_boot = max(
        finals, key=lambda row: _utc(row[0]["retrieved_at"], "bootstrap retrieved_at")
    )
    event = next((row for row in final_boot.get("events", ()) if row.get("id") == gw), None)
    if (
        not event
        or event.get("finished") is not True
        or event.get("data_checked") is not True
        or _utc(event.get("deadline_time", ""), "outcome event deadline") != expected
    ):
        return None
    completion_at = _completion_at(bootstrap, gw, expected_deadline)
    if completion_at is None:
        return None
    final_event = next((row for row in final_boot.get("events", ()) if row.get("id") == 38), None)
    first_event = next((row for row in final_boot.get("events", ()) if row.get("id") == 1), None)
    season_end = (
        _utc(final_event["deadline_time"], "season final deadline")
        if final_event and final_event.get("deadline_time")
        else None
    )
    season_start = (
        _utc(first_event["deadline_time"], "season first deadline")
        if first_event and first_event.get("deadline_time")
        else expected
    )
    upper = (season_end or season_start + timedelta(days=370)) + timedelta(days=30)
    live = [
        (meta, payload)
        for meta, payload, _ in event_live
        if _event(meta) == gw
        and _utc(meta["retrieved_at"], "event-live retrieved_at") >= completion_at
        and _utc(meta["retrieved_at"], "event-live retrieved_at") <= upper
    ]
    if not live:
        return None
    meta, payload = max(
        live, key=lambda row: _utc(row[0]["retrieved_at"], "event-live retrieved_at")
    )
    records = payload.get("elements", ())
    rows = {
        str(row["id"]): row["stats"]
        for row in records
        if isinstance(row, Mapping) and isinstance(row.get("stats"), Mapping)
    }
    if len(rows) != len(records):
        raise ProspectiveValidationError(f"Duplicate or malformed official outcomes for GW{gw}.")
    if meta.get("source_provider") != "official_fpl_api":
        raise ProspectiveValidationError("Outcome snapshot is not from the official local source.")
    return meta, rows, final_meta


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        stop = start + 1
        while stop < len(order) and values[order[stop]] == values[order[start]]:
            stop += 1
        for i in order[start:stop]:
            ranks[i] = (start + stop - 1) / 2
        start = stop
    return ranks


def _metrics(rows: Sequence[Mapping[str, Any]], prediction: str, actual: str) -> dict[str, Any]:
    pairs = [
        (float(row[prediction]), float(row[actual]))
        for row in rows
        if row.get(prediction) is not None and row.get(actual) is not None
    ]
    errors = [p - y for p, y in pairs]
    return {
        "n": len(errors),
        "mae": mean(abs(x) for x in errors) if errors else None,
        "rmse": math.sqrt(mean(x * x for x in errors)) if errors else None,
        "bias": mean(errors) if errors else None,
    }


def _spearman(
    rows: Sequence[Mapping[str, Any]], prediction: str = "xp", actual: str = "points"
) -> float | None:
    if len(rows) < 2:
        return None
    x, y = (
        _rank([float(row[prediction]) for row in rows]),
        _rank([float(row[actual]) for row in rows]),
    )
    mx, my = mean(x), mean(y)
    dx, dy = [v - mx for v in x], [v - my for v in y]
    den = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return sum(a * b for a, b in zip(dx, dy)) / den if den else None


def _history(
    event_live: Sequence[tuple[Mapping[str, Any], Any, Path]],
    bootstrap: Sequence[tuple[Mapping[str, Any], Any, Path]],
    provider_id: str,
    target_gw: int,
    prediction: datetime,
    season_start: datetime,
) -> list[tuple[int, Mapping[str, Any]]]:
    latest: dict[int, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    cutoff_bootstrap = [
        (meta, payload)
        for meta, payload, _ in bootstrap
        if _utc(meta["retrieved_at"], "bootstrap retrieved_at") <= prediction
    ]
    if not cutoff_bootstrap:
        return []
    _, cutoff_payload = max(
        cutoff_bootstrap, key=lambda row: _utc(row[0]["retrieved_at"], "bootstrap retrieved_at")
    )
    for meta, payload, _ in event_live:
        gw = _event(meta)
        retrieved = _utc(meta["retrieved_at"], "event-live retrieved_at")
        if gw >= target_gw or retrieved < season_start or retrieved > prediction:
            continue
        event = next((row for row in cutoff_payload.get("events", ()) if row.get("id") == gw), None)
        if not event or not event.get("deadline_time"):
            continue
        completed_at = _completion_at(bootstrap, gw, event["deadline_time"], prediction)
        if completed_at is None or retrieved < completed_at:
            continue
        element = next(
            (row for row in payload.get("elements", ()) if str(row.get("id")) == provider_id), None
        )
        if element is not None:
            old = latest.get(gw)
            if old is None or retrieved > _utc(old[0]["retrieved_at"], "history retrieved_at"):
                latest[gw] = (meta, element["stats"])
    return [(gw, latest[gw][1]) for gw in sorted(latest)]


def _decision_rows(
    root: Path,
    case: Any,
    outcomes: Mapping[str, Mapping[str, Any]],
    players: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    report = _load(root / case.decision_report.path)
    if report.get("context_id") != case.context_id:
        return [
            {"status": "UNAVAILABLE", "reason": "DecisionReport context does not match archive"}
        ]
    strategic = report.get("policy_results", {}).get("strategic_v3")
    if not isinstance(strategic, Mapping):
        return [{"status": "UNAVAILABLE", "reason": "saved V3 result missing"}]
    preview = strategic.get("path", [{}])
    hold = strategic.get("hold_now_counterfactual", {}).get("path", [{}])
    rows = []
    for label, action in (
        ("saved_v3", preview[0] if preview else None),
        ("saved_v3_hold", hold[0] if hold else None),
    ):
        if (
            not isinstance(action, Mapping)
            or action.get("gw") != case.planning_gameweek
            or action.get("action") not in ("HOLD", "TRANSFER")
            or action.get("chip") not in (None, "NONE")
        ):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "saved action missing or wrong gameweek",
                }
            )
            continue
        squad = action.get("resulting_squad")
        xi = action.get("starting_xi")
        captain = action.get("captain")
        bench = action.get("bench_order")
        vice = action.get("vice_captain")
        if (
            not isinstance(squad, list)
            or len(squad) != 15
            or len(set(squad)) != 15
            or not isinstance(xi, list)
            or len(xi) != 11
            or len(set(xi)) != 11
            or not isinstance(bench, list)
            or len(bench) != 4
            or len(set(bench)) != 4
            or set(xi) & set(bench)
            or set(xi) | set(bench) != set(squad)
            or captain not in xi
            or vice not in xi
            or vice == captain
        ):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "saved XI/squad/captain is incomplete or inconsistent",
                }
            )
            continue
        transfers_out, transfers_in = (
            action.get("transfers_out", []),
            action.get("transfers_in", []),
        )
        frozen_squad = set(case.planning_context.player_ids)
        if (
            not isinstance(transfers_out, list)
            or not isinstance(transfers_in, list)
            or len(transfers_out) != len(set(transfers_out))
            or len(transfers_in) != len(set(transfers_in))
            or len(transfers_out) != len(transfers_in)
            or len(transfers_out) > 2
            or not set(transfers_out) <= frozen_squad
            or set(transfers_in) & frozen_squad
            or set(transfers_out) & set(transfers_in)
            or set(squad) != (frozen_squad - set(transfers_out)) | set(transfers_in)
        ):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "saved action does not reconcile with the archived squad",
                }
            )
            continue
        if label == "saved_v3_hold" and (
            action.get("action") != "HOLD"
            or transfers_out
            or transfers_in
            or set(squad) != frozen_squad
            or action.get("hit_cost_points") != 0
        ):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "frozen HOLD counterfactual is stale or inconsistent",
                }
            )
            continue
        current = strategic.get("current_action", {})
        if label == "saved_v3" and (
            current.get("action") != action.get("action")
            or current.get("transfers_out") != transfers_out
            or current.get("transfers_in") != transfers_in
            or current.get("hit_cost_points") != action.get("hit_cost_points")
        ):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "saved V3 first action does not match current_action",
                }
            )
            continue
        provider_ids = {str(players.get(pid, {}).get("provider_id")) for pid in squad}
        if not provider_ids <= outcomes.keys() or any(not players.get(pid) for pid in squad):
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "not all 15 frozen squad outcomes and player identities are explicit",
                }
            )
            continue
        incomplete_outcome = any(
            not _finite_number(outcomes[str(players[pid]["provider_id"])].get(field))
            for pid in squad
            for field in ("total_points", "minutes")
        )
        if incomplete_outcome:
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "not all 15 frozen squad outcomes have explicit finite points and minutes",
                }
            )
            continue
        hit = action.get("hit_cost_points")
        if not _finite_number(hit) or hit < 0:
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": "frozen hit cost is unavailable",
                }
            )
            continue
        try:
            actual_points = {
                pid: float(outcomes[str(players[pid]["provider_id"])]["total_points"])
                for pid in squad
            }
            appeared = {
                pid: float(outcomes[str(players[pid]["provider_id"])]["minutes"]) > 0
                for pid in squad
            }
            positions = {pid: str(players[pid].get("position")) for pid in squad}
            lineup = evaluate_autosub_lineup(
                gameweek=case.planning_gameweek,
                starter_ids=xi,
                bench_gk_id=bench[0],
                bench_outfield_ids=bench[1:],
                positions=positions,
                expected_points=actual_points,
                p_appearance={pid: float(appeared[pid]) for pid in squad},
            )
        except (AutosubError, KeyError, TypeError, ValueError) as exc:
            rows.append(
                {
                    "status": "UNAVAILABLE",
                    "policy": label,
                    "reason": f"saved lineup cannot be evaluated from explicit outcomes: {type(exc).__name__}",
                }
            )
            continue
        captain_bonus = 0.0
        if appeared[captain]:
            captain_bonus = actual_points[captain]
        elif appeared[vice]:
            captain_bonus = actual_points[vice]
        pts = lineup.total_ev + captain_bonus - float(hit)
        rows.append(
            {
                "status": "SCORED",
                "policy": label,
                "context_id": case.context_id,
                "gameweek": case.planning_gameweek,
                "points": pts,
                "captain": captain,
                "starting_xi": xi,
                "transfers_in": action.get("transfers_in", []),
                "transfers_out": action.get("transfers_out", []),
                "hit_cost_points": hit,
                "autosub_status": "CANONICAL_REALIZED_AUTOSUBS",
                "score_scope": "CURRENT_GW_NO_CHIP_FROZEN_LINEUP_MINUS_HITS",
            }
        )
    return rows


def _render_markdown(report: Mapping[str, Any]) -> str:
    score = report["scorecard"]

    def metric_cells(metric: Mapping[str, Any]) -> str:
        return " | ".join(str(metric.get(key)) for key in ("n", "mae", "rmse", "bias"))

    lines = [
        "# Prospective V22 and saved V3 evaluation",
        "",
        f"Season: {report['season']}  ",
        f"Selected completed gameweeks: {', '.join(map(str, report['selected_gameweeks'])) or 'none'}  ",
        "",
        "Descriptive frozen-evidence evaluation. Forecast GWs are the sampling unit. Historical V3 results are the saved policy version and were not retroactively replayed with current code. Fewer than 20 GWs do not support uncertainty intervals; no IID player-row intervals are reported.",
        "",
        "## V22",
        "",
        "### Points forecast",
        "",
        "| Cohort | N | MAE | RMSE | Bias (xP - points) |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("All players", "all_players"),
        (f"Predicted starters (expected minutes >= {STARTER_MINUTES:g})", "predicted_starters"),
        ("High xP (>= 2)", "high_xp"),
        ("Frozen transfer candidates", "frozen_transfer_candidates"),
        ("Saved XI candidates", "saved_xi_candidates"),
    ):
        lines.append(f"| {label} | {metric_cells(score[key])} |")
    lines.extend(
        [
            "",
            "### Minutes forecast",
            "",
            "| Cohort | N | MAE | RMSE | Bias (predicted - actual) |",
            "|---|---:|---:|---:|---:|",
            f"| All players | {metric_cells(score['minutes'])} |",
            "",
            "### Position groups",
            "",
            "| Position | Points N | Points MAE | Points RMSE | Minutes N | Minutes MAE | Minutes RMSE |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for position in ("GK", "DEF", "MID", "FWD"):
        points = score["by_position"][position]
        minutes = score["minutes_by_position"][position]
        lines.append(
            f"| {position} | {points['n']} | {points['mae']} | {points['rmse']} | {minutes['n']} | {minutes['mae']} | {minutes['rmse']} |"
        )
    lines.extend(
        [
            "",
            "### Predicted-minute buckets",
            "",
            "| Bucket | Points N | Points MAE | Minutes N | Minutes MAE |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for bucket, points in score["by_predicted_minutes"].items():
        minutes = score["minutes_by_predicted_minutes"][bucket]
        lines.append(
            f"| {bucket} | {points['n']} | {points['mae']} | {minutes['n']} | {minutes['mae']} |"
        )
    lines.extend(
        [
            "",
            "## Same-row baselines",
            "",
            "Each comparison uses only rows with both a V22 forecast and a complete historical baseline value. Recent-history baselines average up to three available completed gameweeks; each row records the contributing gameweeks and count.",
            "",
            "| Cohort | Baseline | Matched N | V22 MAE | Baseline MAE | Baseline RMSE |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for cohort, group_key in (
        ("All players", "all_players"),
        ("Predicted starters", "predicted_starters"),
        ("High xP", "high_xp"),
        ("Frozen transfer candidates", "frozen_transfer_candidates"),
        ("Saved XI candidates", "saved_xi_candidates"),
    ):
        for label, key in (
            ("Previous completed GW points", "previous_gw"),
            ("Recent up to three completed GWs", "recent3"),
            ("Recent points per minute x predicted minutes", "minutes_aware"),
        ):
            baseline = score["baseline_by_group"][group_key][key]
            lines.append(
                f"| {cohort} | {label} | {baseline['n']} | {baseline['v22']['mae']} | {baseline['baseline']['mae']} | {baseline['baseline']['rmse']} |"
            )
    lines.extend(
        [
            "",
            "## Per-gameweek metrics",
            "",
            "| GW | Point N | Point MAE | Point RMSE | Minutes N | Minutes MAE | Minutes RMSE |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for gw, metrics in score["by_gameweek"].items():
        points, minutes = metrics["points"], metrics["minutes"]
        lines.append(
            f"| {gw} | {points['n']} | {points['mae']} | {points['rmse']} | {minutes['n']} | {minutes['mae']} | {minutes['rmse']} |"
        )
    lines.extend(
        [
            "",
            "## Saved V3 versus frozen HOLD",
            "",
            "Same-context, no-chip current-GW counterfactuals use saved XI/bench order, observed outcomes, the canonical exact autosub evaluator, captain/vice fallback and frozen hits. No lineup is selected with hindsight. Terminal FT value and future planned actions are not realised points here; these scores do not establish current-policy superiority.",
            "",
            "| GW | V3 points | HOLD points | V3 - HOLD |",
            "|---:|---:|---:|---:|",
        ]
    )
    pairs = score["saved_v3_vs_hold_paired"]["by_gameweek"]
    for gw, pair in pairs.items():
        lines.append(
            f"| {gw} | {pair['v3_points']} | {pair['hold_points']} | {pair['v3_minus_hold_points']} |"
        )
    if not pairs:
        lines.append("| None scored | Unavailable | Unavailable | Unavailable |")
    paired = score["saved_v3_vs_hold_paired"]
    lines.extend(
        [
            "",
            f"Paired GWs: {paired['n_gameweeks']}; mean V3 - HOLD: {paired['mean_v3_minus_hold_points']}; total gain: {paired['total_v3_minus_hold_points']}.",
            "",
            "Baselines are matched to the same player-GW rows. Missing history values are excluded rather than imputed.",
            "",
            "## Selection and exclusions",
            "",
            f"Primary archives: {len(report['primary_archives'])}; exclusions: {len(report['exclusions'])}.",
            "",
            "## Decision evidence",
            "",
        ]
    )
    for row in report["decision_scores"]:
        lines.append(
            f"GW{row.get('gameweek', '?')} {row.get('policy', '')}: {row.get('status')} — {row.get('points', row.get('reason', ''))}"
        )
    return "\n".join(lines) + "\n"


def _evaluate_locked(
    root: Path,
    season: str,
    output_dir: Path,
    gw_min: int | None = None,
    gw_max: int | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate verified local archives without calling prediction or provider code."""
    root, output_dir = Path(root).resolve(), Path(output_dir).resolve()
    if not season or (gw_min is not None and gw_max is not None and gw_min > gw_max):
        raise ProspectiveValidationError(
            "Provide an explicit season and a valid optional GW range."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = Path(ledger_path).resolve() if ledger_path else output_dir / "primary-locks.jsonl"
    inventory: dict[str, str] = {}
    raw_exclusions: list[dict[str, str]] = []
    bootstrap = _snapshots(root, "bootstrap_static", inventory, raw_exclusions)
    live = _snapshots(root, "event_live", inventory, raw_exclusions)
    gws = list(range(gw_min or 1, (gw_max or 38) + 1))
    selected, exclusions, new_locks = _select_archives(root, season, gws, bootstrap, ledger)
    exclusions.extend(
        {"reason": "raw snapshot unavailable or failed hash validation", **item}
        for item in raw_exclusions
    )
    outcome_cache = {
        gw: _official_outcomes(live, bootstrap, gw, selected[gw][1].official_deadline)
        if gw in selected
        else None
        for gw in gws
    }
    rows: list[dict[str, Any]] = []
    decision_scores: list[dict[str, Any]] = []
    primary = []
    for gw, (archive_path, case, validation) in sorted(selected.items()):
        primary_entry = {
            "gameweek": gw,
            "archive_path": str(archive_path.relative_to(root)).replace("\\", "/"),
            "archive_sha256": _hash(archive_path),
            "projection_bundle": case.projection_bundle.path,
            "projection_bundle_sha256": case.projection_bundle.sha256,
            "projection_manifest_sha256": case.projection_manifest.sha256,
            "prediction_timestamp": case.planning_context.prediction_timestamp,
            "official_deadline": case.official_deadline,
            "context_id": case.context_id,
            "archive_validation": validation,
        }
        primary.append(primary_entry)
        outcome = outcome_cache.get(gw)
        if outcome is None:
            primary_entry["outcome_availability"] = "PENDING_OR_UNAVAILABLE"
            exclusions.append(
                {
                    "gameweek": gw,
                    "archive": str(archive_path.relative_to(root)),
                    "reason": "official completion or data_checked outcome snapshot unavailable",
                }
            )
            continue
        outcome_meta, actual_by_provider, completion_meta = outcome
        primary_entry.update(
            {
                "outcome_availability": "AVAILABLE",
                "outcome_snapshot_id": outcome_meta.get("snapshot_id"),
                "completion_snapshot_id": completion_meta.get("snapshot_id"),
            }
        )
        bundle_path = root / case.projection_bundle.path
        bundle = _load(bundle_path, inventory)
        manifest = _load(root / case.projection_manifest.path, inventory)
        player_path = bundle_path.parent / "current_players.json"
        players_list = _load(player_path, inventory)
        players = {
            row["player_id"]: row
            for row in players_list
            if isinstance(row, Mapping) and "player_id" in row
        }
        provider_ids = [
            str(row.get("provider_id")) for row in players_list if isinstance(row, Mapping)
        ]
        if (
            len(players) != len(players_list)
            or len(provider_ids) != len(players_list)
            or len(set(provider_ids)) != len(provider_ids)
        ):
            raise ProspectiveValidationError(
                f"Duplicate/missing frozen player or provider IDs in GW{gw} player snapshot."
            )
        prediction = _utc(case.planning_context.prediction_timestamp, "prediction timestamp")
        bootstrap_at_prediction = [
            p
            for p in bootstrap
            if _utc(p[0]["retrieved_at"], "bootstrap retrieved_at") <= prediction
        ]
        if not bootstrap_at_prediction:
            exclusions.append(
                {
                    "gameweek": gw,
                    "archive": str(archive_path.relative_to(root)),
                    "reason": "no official identity snapshot available by prediction time",
                }
            )
            continue
        identity_meta, identity_body, _ = max(
            bootstrap_at_prediction,
            key=lambda item: _utc(item[0]["retrieved_at"], "bootstrap retrieved_at"),
        )
        identities = {
            str(row["id"]): row for row in identity_body.get("elements", ()) if "id" in row
        }
        season_start_raw, _ = _official_deadline(bootstrap, 1, prediction)
        if not season_start_raw:
            exclusions.append(
                {
                    "gameweek": gw,
                    "archive": str(archive_path.relative_to(root)),
                    "reason": "season start deadline unavailable in local official snapshots",
                }
            )
            continue
        season_start = _utc(season_start_raw, "season first deadline")
        decision_report = _load(root / case.decision_report.path)
        analysis_manifest = _load(root / case.analysis_manifest.path, inventory)
        v3 = decision_report.get("policy_results", {}).get("strategic_v3", {})
        transfer_candidates = _walk_transfer_ids(
            {
                "v3": {
                    "current_action": v3.get("current_action"),
                    "first_action": v3.get("path", [{}])[0] if v3.get("path") else {},
                },
                "previews": decision_report.get("strategy_previews", {}),
                "feasible_plans": decision_report.get("feasible_plans", []),
            }
        )
        captain_candidates = set()
        saved_path = v3.get("path", []) if isinstance(v3, Mapping) else []
        if saved_path and isinstance(saved_path[0], Mapping):
            captain_candidates.update(str(pid) for pid in saved_path[0].get("starting_xi", []))
        seen_projection_ids: set[str] = set()
        for projection in bundle.get("projections", ()):
            pid = projection.get("player_id")
            if pid in seen_projection_ids:
                raise ProspectiveValidationError(
                    f"Duplicate projected player in GW{gw} bundle: {pid}"
                )
            seen_projection_ids.add(pid)
            player = players.get(pid)
            provider = str(player.get("provider_id")) if player else ""
            current_identity = identities.get(provider)
            if (
                not player
                or not current_identity
                or str(player.get("provider_payload", {}).get("code"))
                != str(current_identity.get("code"))
            ):
                exclusions.append(
                    {
                        "gameweek": gw,
                        "player_id": pid,
                        "reason": "missing official identity or stable code mismatch at prediction time",
                    }
                )
                continue
            target = next(
                (
                    row
                    for row in projection.get("gameweeks", ())
                    if row.get("target_gameweek") == gw
                ),
                None,
            )
            if target is None:
                exclusions.append(
                    {
                        "gameweek": gw,
                        "player_id": pid,
                        "reason": "target gameweek projection missing",
                    }
                )
                continue
            actual = actual_by_provider.get(provider)
            if actual is None:
                exclusions.append(
                    {
                        "gameweek": gw,
                        "player_id": pid,
                        "reason": "missing explicit outcome row; never imputed zero",
                    }
                )
                continue
            numeric = (
                target.get("expected_points"),
                target.get("expected_minutes"),
                actual.get("total_points"),
                actual.get("minutes"),
            )
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in numeric
            ):
                exclusions.append(
                    {
                        "gameweek": gw,
                        "player_id": pid,
                        "reason": "non-finite or missing points/minutes value",
                    }
                )
                continue
            probabilities = [target.get(f"p_{threshold}_plus") for threshold in (5, 8, 10, 15)]
            if any(
                value is not None
                and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                )
                for value in probabilities
            ):
                exclusions.append(
                    {
                        "gameweek": gw,
                        "player_id": pid,
                        "reason": "invalid saved probability outside [0,1]",
                    }
                )
                continue
            row = {
                "season": season,
                "gameweek": gw,
                "player_id": pid,
                "provider_id": provider,
                "position": player.get("position"),
                "xp": target.get("expected_points"),
                "predicted_minutes": target.get("expected_minutes"),
                "points": actual.get("total_points"),
                "minutes": actual.get("minutes"),
                "goals": actual.get("goals_scored"),
                "assists": actual.get("assists"),
                "fixtures": target.get("fixture_count"),
                "forecast_age_hours": (
                    _utc(case.official_deadline, "deadline") - prediction
                ).total_seconds()
                / 3600,
                "transfer_candidate": pid in transfer_candidates,
                "captain_candidate": pid in captain_candidates,
            }
            row.update(
                {
                    k: target.get(k)
                    for k in ("p_5_plus", "p_8_plus", "p_10_plus", "p_15_plus", "p_return")
                }
            )
            history = _history(live, bootstrap, provider, gw, prediction, season_start)
            if history:
                previous = history[-1][1]
                recent = history[-3:]
                row["baseline_history_gameweeks"] = [history_gw for history_gw, _ in recent]
                row["baseline_history_count"] = len(recent)
                if _finite_number(previous.get("total_points")):
                    row["baseline_previous"] = float(previous["total_points"])
                else:
                    exclusions.append(
                        {
                            "gameweek": gw,
                            "player_id": pid,
                            "reason": "previous-GW baseline missing explicit finite points; excluded from baseline comparison",
                        }
                    )
                complete_points = all(_finite_number(h.get("total_points")) for _, h in recent)
                complete_minutes = all(_finite_number(h.get("minutes")) for _, h in recent)
                if complete_points:
                    row["baseline_recent3"] = mean(float(h["total_points"]) for _, h in recent)
                else:
                    exclusions.append(
                        {
                            "gameweek": gw,
                            "player_id": pid,
                            "reason": "recent-history baseline missing explicit finite points; excluded from baseline comparison",
                        }
                    )
                total_minutes = (
                    sum(float(h["minutes"]) for _, h in recent) if complete_minutes else 0.0
                )
                if complete_points and complete_minutes and total_minutes > 0:
                    row["baseline_minutes_aware"] = (
                        sum(float(h["total_points"]) for _, h in recent)
                        / total_minutes
                        * float(row["predicted_minutes"] or 0)
                    )
                elif not complete_points or not complete_minutes:
                    exclusions.append(
                        {
                            "gameweek": gw,
                            "player_id": pid,
                            "reason": "minutes-aware baseline missing explicit finite points/minutes; excluded from baseline comparison",
                        }
                    )
            rows.append(row)
        decision_scores.extend(_decision_rows(root, case, actual_by_provider, players))
        primary_entry.update(
            {
                "model_versions": manifest.get("model_versions", []),
                "configuration_hashes": manifest.get("configuration_hashes", {}),
                "deadline_snapshot_id": _official_deadline(bootstrap, gw, prediction)[1],
                "identity_snapshot_id": identity_meta.get("snapshot_id"),
                "historical_v3_version": v3.get("version") if isinstance(v3, Mapping) else None,
                "capture_source_identities": analysis_manifest.get("prospective_capture"),
            }
        )

    groups = {
        "all_players": list(rows),
        "predicted_starters": [
            r
            for r in rows
            if isinstance(r.get("predicted_minutes"), (int, float))
            and r["predicted_minutes"] >= STARTER_MINUTES
        ],
        "high_xp": [r for r in rows if isinstance(r.get("xp"), (int, float)) and r["xp"] >= 2],
        "frozen_transfer_candidates": [r for r in rows if r["transfer_candidate"]],
        "saved_xi_candidates": [r for r in rows if r["captain_candidate"]],
    }
    scorecard: dict[str, Any] = {
        name: _metrics(group, "xp", "points") for name, group in groups.items()
    }
    scorecard["minutes"] = _metrics(rows, "predicted_minutes", "minutes")
    scorecard["by_position"] = {
        str(position): _metrics([r for r in rows if r.get("position") == position], "xp", "points")
        for position in ("GK", "DEF", "MID", "FWD")
    }
    scorecard["minutes_by_position"] = {
        str(position): _metrics(
            [r for r in rows if r.get("position") == position],
            "predicted_minutes",
            "minutes",
        )
        for position in ("GK", "DEF", "MID", "FWD")
    }
    scorecard["by_predicted_minutes"] = {
        label: _metrics(
            [
                r
                for r in rows
                if isinstance(r.get("predicted_minutes"), (int, float))
                and low <= r["predicted_minutes"] < high
            ],
            "xp",
            "points",
        )
        for label, low, high in (
            ("[0,1)", 0, 1),
            ("[1,30)", 1, 30),
            ("[30,60)", 30, 60),
            ("[60,80)", 60, 80),
            ("[80,inf)", 80, math.inf),
        )
    }
    scorecard["minutes_by_predicted_minutes"] = {
        label: _metrics(
            [
                r
                for r in rows
                if isinstance(r.get("predicted_minutes"), (int, float))
                and low <= r["predicted_minutes"] < high
            ],
            "predicted_minutes",
            "minutes",
        )
        for label, low, high in (
            ("[0,1)", 0, 1),
            ("[1,30)", 1, 30),
            ("[30,60)", 30, 60),
            ("[60,80)", 60, 80),
            ("[80,inf)", 80, math.inf),
        )
    }
    scorecard["by_gameweek"] = {
        str(gw): {
            "points": _metrics([r for r in rows if r["gameweek"] == gw], "xp", "points"),
            "minutes": _metrics(
                [r for r in rows if r["gameweek"] == gw], "predicted_minutes", "minutes"
            ),
        }
        for gw in sorted({r["gameweek"] for r in rows})
    }
    scorecard["observed_returns"] = {
        "goals_mean": mean(
            float(r["goals"]) for r in rows if isinstance(r.get("goals"), (int, float))
        )
        if any(isinstance(r.get("goals"), (int, float)) for r in rows)
        else None,
        "assists_mean": mean(
            float(r["assists"]) for r in rows if isinstance(r.get("assists"), (int, float))
        )
        if any(isinstance(r.get("assists"), (int, float)) for r in rows)
        else None,
    }
    scorecard["assists_observed_mean"] = (
        mean(float(r["assists"]) for r in rows if isinstance(r.get("assists"), (int, float)))
        if any(isinstance(r.get("assists"), (int, float)) for r in rows)
        else None
    )
    for name, key in (
        ("baseline_previous", "previous_gw"),
        ("baseline_recent3", "recent3"),
        ("baseline_minutes_aware", "minutes_aware"),
    ):
        matched = [r for r in rows if r.get(name) is not None]
        scorecard[key] = {
            "n": len(matched),
            "v22": _metrics(matched, "xp", "points"),
            "baseline": _metrics(matched, name, "points"),
        }
    scorecard["baseline_by_group"] = {}
    for group_name, group_rows in groups.items():
        scorecard["baseline_by_group"][group_name] = {}
        for name, key in (
            ("baseline_previous", "previous_gw"),
            ("baseline_recent3", "recent3"),
            ("baseline_minutes_aware", "minutes_aware"),
        ):
            matched = [row for row in group_rows if row.get(name) is not None]
            scorecard["baseline_by_group"][group_name][key] = {
                "n": len(matched),
                "v22": _metrics(matched, "xp", "points"),
                "baseline": _metrics(matched, name, "points"),
            }
    scorecard["spearman_by_gw"] = {
        str(gw): _spearman([r for r in rows if r["gameweek"] == gw])
        for gw in sorted({r["gameweek"] for r in rows})
    }
    scorecard["brier"] = {}
    for threshold in (5, 8, 10, 15):
        field = f"p_{threshold}_plus"
        matched = [r for r in rows if isinstance(r.get(field), (int, float))]
        scorecard["brier"][field] = {
            "n": len(matched),
            "score": mean(
                (float(r[field]) - (float(r["points"]) >= threshold)) ** 2 for r in matched
            )
            if matched
            else None,
        }
    paired_by_gw = {}
    for gw in sorted({r.get("gameweek") for r in decision_scores if r.get("status") == "SCORED"}):
        pair = {
            row.get("policy"): row
            for row in decision_scores
            if row.get("status") == "SCORED" and row.get("gameweek") == gw
        }
        v3, hold = pair.get("saved_v3"), pair.get("saved_v3_hold")
        if v3 and hold and v3.get("context_id") == hold.get("context_id"):
            paired_by_gw[str(gw)] = {
                "context_id": v3["context_id"],
                "v3_points": v3["points"],
                "hold_points": hold["points"],
                "v3_minus_hold_points": v3["points"] - hold["points"],
            }
    scorecard["saved_v3_vs_hold_paired"] = {
        "by_gameweek": paired_by_gw,
        "n_gameweeks": len(paired_by_gw),
        "mean_v3_minus_hold_points": mean(
            row["v3_minus_hold_points"] for row in paired_by_gw.values()
        )
        if paired_by_gw
        else None,
        "total_v3_minus_hold_points": sum(
            row["v3_minus_hold_points"] for row in paired_by_gw.values()
        )
        if paired_by_gw
        else None,
        "interpretation": "descriptive saved historical previews on the same archived context; current V3 was not replayed",
    }
    input_hashes = {}
    for path, digest in sorted(inventory.items()):
        try:
            name = Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            name = path
        input_hashes[name] = digest
    try:
        ledger_reference = ledger.relative_to(root).as_posix()
    except ValueError:
        ledger_reference = str(ledger)
    report = {
        "schema_version": SCHEMA,
        "season": season,
        "selection_rule": "latest prediction timestamp among canonical V22 archives created strictly before official deadline and passing archive/hash/PIT checks; first selected archive is SHA-256 locked",
        "selected_gameweeks": sorted({r["gameweek"] for r in rows}),
        "primary_gameweeks": sorted(row["gameweek"] for row in primary),
        "minimum_gameweeks_for_uncertainty": MIN_GWS_FOR_UNCERTAINTY,
        "uncertainty_status": "NOT_ESTIMATED_TOO_FEW_GW_CLUSTERS"
        if len({r["gameweek"] for r in rows}) < MIN_GWS_FOR_UNCERTAINTY
        else "DESCRIPTIVE_ONLY_NO_IID_ROW_INTERVALS",
        "primary_archives": primary,
        "exclusions": exclusions,
        "scorecard": scorecard,
        "rows": rows,
        "decision_scores": decision_scores,
        "input_sha256": input_hashes,
        "ledger_path": ledger_reference,
    }
    json_path, md_path = output_dir / "report.json", output_dir / "report.md"
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    markdown = _render_markdown(report)
    if new_locks:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8", newline="\n") as stream:
            for lock in new_locks:
                stream.write(json.dumps(lock, sort_keys=True) + "\n")
            stream.flush()
    for path, content in ((json_path, payload), (md_path, markdown)):
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != content:
                raise ProspectiveValidationError(f"Refusing to replace immutable report: {path}")
    return report


def evaluate(
    root: Path,
    season: str,
    output_dir: Path,
    gw_min: int | None = None,
    gw_max: int | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Serialize evaluations sharing a primary ledger and preserve immutable reports."""
    output_dir = Path(output_dir).resolve()
    ledger = Path(ledger_path).resolve() if ledger_path else output_dir / "primary-locks.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger.with_name(ledger.name + ".lock")
    try:
        with lock_path.open("x", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\n")
    except FileExistsError as exc:
        raise ProspectiveValidationError(
            f"Selection ledger is locked: {lock_path}; verify no evaluation is active before removing a stale lock."
        ) from exc
    try:
        return _evaluate_locked(root, season, output_dir, gw_min, gw_max, ledger)
    finally:
        # shortcut: abrupt process termination can leave this lock; remove only after confirming no run is active.
        lock_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="Explicit season, e.g. 2026/27")
    parser.add_argument("--output", required=True, type=Path, help="New immutable report directory")
    parser.add_argument("--gw-min", type=int)
    parser.add_argument("--gw-max", type=int)
    parser.add_argument(
        "--ledger", type=Path, help="Append-only selection ledger shared across reruns"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        report = evaluate(
            args.root, args.season, args.output, args.gw_min, args.gw_max, args.ledger
        )
    except (OSError, ProspectiveValidationError, ReplayArchiveError) as exc:
        print(f"prospective validation failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "selected_gameweeks": report["selected_gameweeks"],
                "v22_all_players": report["scorecard"]["all_players"],
                "report": str(args.output / "report.md"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

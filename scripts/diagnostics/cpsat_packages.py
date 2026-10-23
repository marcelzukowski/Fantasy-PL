"""Phase1 diagnostic adapter: canonical input/accounting and independent native replay."""

from collections.abc import Mapping
from dataclasses import asdict, replace
from decimal import Decimal, ROUND_HALF_EVEN
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import subprocess
from time import perf_counter

from fpl_engine.optimizer import next_free_transfers, selling_price, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config

ROOT = Path(__file__).resolve().parents[2]
SCALE = 1_000_000
OBJECTIVE = "sum ALL15 existing ev_next_3 signals, scaled half-even, minus native transfer hits; NOT full V3"


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
        ).encode()
    ).hexdigest()


def _pool_rows(pool):
    rows = list(pool.values() if isinstance(pool, Mapping) else pool)
    if len({p.player_id for p in rows}) != len(rows):
        raise ValueError("Duplicate player IDs in candidate pool")
    return {p.player_id: p for p in rows}


def prepare_problem(state, pool, projections, rules):
    validate_squad(state, rules)
    owned = {p.player_id: p for p in state.players}
    rows = _pool_rows(pool)
    rows.update(owned)
    prepared, excluded = [], []
    for pid, player in sorted(rows.items()):
        projection = projections.get(pid)
        if projection is None:
            if pid in owned:
                raise ValueError("Owned player is missing projection: " + pid)
            excluded.append({"player_id": pid, "reason": "missing projection"})
            continue
        if (
            projection.player_id != pid
            or projection.season != state.season
            or projection.rule_version != state.rule_version
            or projection.current_gameweek != state.current_gameweek
            or projection.prediction_timestamp != state.prediction_timestamp
        ):
            raise ValueError("Projection context mismatch: " + pid)
        signal = Decimal(str(projection.ev_next_3))
        if not signal.is_finite():
            raise ValueError("Nonfinite projection signal: " + pid)
        price = (
            (
                player.selling_price
                if player.selling_price is not None
                else selling_price(player.purchase_price, player.current_price, rules)
            )
            if pid in owned
            else player.current_price
        )
        if type(price) is not int or price < 0 or price >= 2**40:
            raise ValueError("Invalid/unsafe integer price: " + pid)
        weight = int((signal * SCALE).to_integral_value(rounding=ROUND_HALF_EVEN))
        prepared.append(
            {
                "player_id": pid,
                "position": player.position,
                "club_id": player.club_id,
                "owned": pid in owned,
                "price": price,
                "weight": weight,
            }
        )
    if sum(abs(p["weight"]) for p in prepared) >= 2**50:
        raise ValueError("Unsafe surrogate coefficient range")
    # Read the configured canonical hit unit once; every returned action is
    # independently compared to native transfer construction below.
    hit_unit = int(
        rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance")
    )
    accounting = {
        str(k): {
            "hit_cost_points": max(0, k - state.free_transfers) * hit_unit,
            "free_transfers_after": next_free_transfers(state.free_transfers, k, rules),
        }
        for k in range(6)
    }
    problem = {
        "model_version": "diagnostic_cpsat_packages_phase1",
        "players": prepared,
        "squad_size": int(rules.value("initial_squad", "squad_size")),
        "position_quotas": {
            v["canonical_code"]: int(v["squad_count"]) for v in rules.value("positions").values()
        },
        "max_per_club": int(rules.value("initial_squad", "maximum_players_per_club")),
        "bank": state.bank,
        "free_transfers": state.free_transfers,
        "hit_unit": hit_unit,
        "accounting_by_k": accounting,
        "objective_scale": SCALE,
        "objective_description": OBJECTIVE,
        "max_rounding_error_points": len(state.players) / (2 * SCALE),
        "excluded_candidates": excluded,
        "state_sha256": digest(asdict(state)),
        "rules_sha256": digest(rules.raw),
    }
    problem["input_sha256"] = digest(problem)
    return problem


def validate_packages(problem, state, pool, rules, result):
    if result.get("input_sha256") != problem["input_sha256"]:
        raise ValueError("Worker input digest mismatch")
    if set(result.get("packages_by_k", {})) != {str(k) for k in range(6)}:
        raise ValueError("Missing K allocation")
    allowed_statuses = {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"}
    attempts = {}
    for attempt in result["attempts"]:
        if attempt["status"] not in allowed_statuses:
            raise ValueError("Unknown solver status")
        identity = (attempt["k"], attempt["rank"])
        if identity in attempts or attempt["k"] not in range(6):
            raise ValueError("Duplicate/invalid solver attempt")
        attempts[identity] = attempt
        if attempt["status"] not in {"OPTIMAL", "FEASIBLE"} and (
            attempt.get("objective_scaled") is not None
            or attempt.get("objective_bound_scaled") is not None
        ):
            raise ValueError("No-solution status has a fabricated objective")
    planner = StrategicPlannerV3(
        rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
    )
    owned = {p.player_id: p for p in state.players}
    candidates = _pool_rows(pool)
    weights = {p["player_id"]: p["weight"] for p in problem["players"]}
    for k in range(6):
        seen = set()
        if len(result["packages_by_k"][str(k)]) > 5:
            raise ValueError("Per-K allocation exceeded")
        for package in result["packages_by_k"][str(k)]:
            outs, ins = package["transfers_out"], package["transfers_in"]
            if (
                len(outs) != k
                or len(ins) != k
                or len(set(outs)) != k
                or len(set(ins)) != k
                or outs != sorted(outs)
                or ins != sorted(ins)
                or set(outs) & set(ins)
                or not set(outs) <= set(owned)
                or set(ins) & set(owned)
                or not set(ins) <= set(weights)
            ):
                raise ValueError("Invalid OUT/IN identity")
            if k:
                action = planner._make_action(
                    state, tuple(owned[x] for x in outs), tuple(candidates[x] for x in ins)
                )
                if action is None:
                    raise ValueError("Worker returned natively illegal package")
                expected = {
                    "resulting_squad": list(action.resulting_squad),
                    "resulting_bank": action.resulting_bank,
                    "hit_cost_points": action.hit_cost_points,
                    "free_transfers_after": action.free_transfers_after,
                }
                final_players = tuple(p for p in state.players if p.player_id not in outs) + tuple(
                    replace(
                        candidates[x],
                        purchase_price=candidates[x].current_price,
                        selling_price=candidates[x].current_price,
                    )
                    for x in ins
                )
            else:
                expected = {
                    "resulting_squad": sorted(owned),
                    "resulting_bank": state.bank,
                    "hit_cost_points": 0,
                    "free_transfers_after": next_free_transfers(state.free_transfers, 0, rules),
                }
                final_players = state.players
            if (
                any(package.get(key) != value for key, value in expected.items())
                or package.get("free_transfers_before") != state.free_transfers
            ):
                raise ValueError("Native package finance/FT/squad mismatch")
            validate_squad(
                replace(
                    state,
                    players=final_players,
                    bank=expected["resulting_bank"],
                    free_transfers=expected["free_transfers_after"],
                ),
                rules,
            )
            identity = tuple(expected["resulting_squad"])
            if identity in seen:
                raise ValueError("Duplicate final roster")
            seen.add(identity)
            score = sum(weights[pid] for pid in identity) - expected["hit_cost_points"] * SCALE
            if package["objective_scaled"] != score or package["status"] not in {
                "OPTIMAL",
                "FEASIBLE",
            }:
                raise ValueError("Surrogate/status mismatch")
            bound = package["objective_bound_scaled"]
            if (
                not isfinite(bound)
                or bound < score
                or (package["status"] == "OPTIMAL" and bound != score)
            ):
                raise ValueError("Invalid objective bound")
            attempt = attempts.get((k, package["rank"]))
            if attempt is None or any(
                package[field] != attempt[field]
                for field in (
                    "status",
                    "objective_scaled",
                    "objective_bound_scaled",
                    "excluded_squads",
                )
            ):
                raise ValueError("Package does not match recorded solver attempt")
            package["native_legality"] = "PASS"
    return result


def generate_packages(
    state, pool, projections, rules, *, candidates_per_k=5, time_limit_seconds=1.0
):
    started = perf_counter()
    pool = _pool_rows(pool)
    problem = prepare_problem(state, pool, projections, rules)
    if (
        type(candidates_per_k) is not int
        or not 1 <= candidates_per_k <= 5
        or not 0 < time_limit_seconds <= 10
    ):
        raise ValueError("Expected allocation1..5 and time limit(0,10] seconds")
    python = ROOT / ".venv-solver/Scripts/python.exe"
    if not python.is_file():
        raise FileNotFoundError("Isolated .venv-solver Python is unavailable")
    try:
        response = subprocess.run(
            [str(python), str(ROOT / "scripts/diagnostics/cpsat_worker.py")],
            input=json.dumps(
                {
                    "problem": problem,
                    "options": {
                        "candidates_per_k": candidates_per_k,
                        "time_limit_seconds": time_limit_seconds,
                    },
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            check=True,
            timeout=6 * candidates_per_k * time_limit_seconds + 30,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Isolated CP-SAT worker failed:\n" + (exc.stderr or "")) from exc
    result = validate_packages(problem, state, pool, rules, json.loads(response.stdout))
    result.update(
        problem=problem, total_seconds=perf_counter() - started, full_v3_objective_modeled=False
    )
    return result

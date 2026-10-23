"""Local manual scenarios; never writes squad state or production reports."""

from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import tempfile
from uuid import uuid4


class ScenarioStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self, *, validate_results=True):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                type(data["schema_version"]) is not int
                or data["schema_version"] != 1
                or not isinstance(data["scenarios"], list)
            ):
                raise ValueError
            rows = data["scenarios"]
            if len({r["id"] for r in rows}) != len(rows):
                raise ValueError
            for row in rows:
                if not all(
                    isinstance(row[k], str) for k in ("id", "name", "context_id", "input_sha256")
                ):
                    raise ValueError
                self._package(row["transfers_out"], row["transfers_in"])
                if validate_results:
                    try:
                        if row.get("status") == "evaluated" and row.get("result") is None:
                            raise ValueError("Saved evaluation is missing.")
                        self._result(
                            row.get("result"),
                            row["context_id"],
                            row["input_sha256"],
                            row["transfers_out"],
                            row["transfers_in"],
                        )
                        row["status"] = "evaluated" if row.get("result") else "pending"
                    except ValueError as exc:
                        row["result"] = None
                        row["status"] = "invalid"
                        row["result_error"] = str(exc) + " Re-evaluate these selections."
            return rows
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Saved scenarios are unreadable; the existing file was preserved."
            ) from exc

    @staticmethod
    def _package(outs, ins):
        if (
            not isinstance(outs, list)
            or not isinstance(ins, list)
            or len(outs) != len(ins)
            or len(outs) > 5
            or any(not isinstance(p, str) or not p for p in outs + ins)
            or len(set(outs)) != len(outs)
            or len(set(ins)) != len(ins)
            or set(outs) & set(ins)
        ):
            raise ValueError("Scenario needs matching, distinct OUT/IN sets with K0..5.")

    def _write(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            dir=self.path.parent, prefix="manual-scenarios-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(
                    {"schema_version": 1, "scenarios": rows},
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _result(result, context_id, input_sha256, outs, ins):
        if result is None:
            return
        if (
            not isinstance(result, dict)
            or result.get("context_id") != context_id
            or result.get("input_sha256") != input_sha256
        ):
            raise ValueError("Scenario result belongs to a different context.")

        def number(value):
            if type(value) not in (int, float) or not isfinite(value):
                raise ValueError("Invalid numeric result field.")
            return value

        def integer(value, low, high):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid integer result field.")
            return value

        def equal(left, right):
            if abs(number(left) - number(right)) > 1e-9:
                raise ValueError("Result arithmetic is inconsistent.")

        def lineup(value):
            xi, bench = value["starting_xi"], value["bench_order"]
            if (
                not isinstance(xi, list)
                or not isinstance(bench, list)
                or len(xi) != 11
                or len(bench) != 4
                or any(not isinstance(pid, str) or not pid for pid in xi + bench)
                or len(set(xi + bench)) != 15
                or value["captain"] not in xi
                or value["vice_captain"] not in xi
                or value["captain"] == value["vice_captain"]
            ):
                raise ValueError("Invalid XI, bench or captain identities.")
            return set(xi + bench)

        try:
            if type(result["cached"]) is not bool:
                raise ValueError("Invalid cache status.")
            scenario, hold, production = (result[key] for key in ("scenario", "hold", "production"))
            roots, gameweeks, initial_fts = [], [], []
            for item in (scenario, hold, production):
                ScenarioStore._package(item["transfers_out"], item["transfers_in"])
                k = integer(item["k"], 0, 5)
                if k != len(item["transfers_out"]):
                    raise ValueError("Transfer count mismatch.")
                initial_fts.append(integer(item["initial_ft"], 0, 5))
                integer(item["ft_after"], 0, 5)
                integer(item["bank_after"], 0, 100000)
                integer(item["hit_points"], 0, 20)
                path = item["path"]
                if not isinstance(path, list) or len(path) != 3:
                    raise ValueError("Expected a complete three-gameweek path.")
                total, previous, first_gw = 0.0, None, None
                for offset, step in enumerate(path):
                    gw = integer(step["gw"], 1, 38)
                    if offset == 0:
                        first_gw = gw
                    if gw != first_gw + offset:
                        raise ValueError("Path gameweeks are inconsistent.")
                    step_out, step_in = step["transfers_out"], step["transfers_in"]
                    ScenarioStore._package(step_out, step_in)
                    if offset and len(step_out) > 2:
                        raise ValueError("Future path exceeds the native transfer limit.")
                    roster = lineup(step)
                    if not set(step_in) <= roster or set(step_out) & roster:
                        raise ValueError("Transfers disagree with the resulting lineup.")
                    before = roster - set(step_in) | set(step_out)
                    if previous is not None and before != previous:
                        raise ValueError("Path squad identities are inconsistent.")
                    if offset == 0:
                        roots.append(before)
                    previous = roster
                    hit = integer(step["hit_points"], 0, 20)
                    total += number(step["lineup_points"]) - hit
                gameweeks.append(first_gw)
                lineup(item)
                for field in (
                    "transfers_out",
                    "transfers_in",
                    "starting_xi",
                    "bench_order",
                    "captain",
                    "vice_captain",
                    "hit_points",
                ):
                    if item[field] != path[0][field]:
                        raise ValueError("Current action disagrees with the first path step.")
                equal(item["path_points"], total)
                equal(item["objective"], total + number(item["terminal_ft_value"]))
                equal(item["delta_hold"], item["objective"] - number(hold["objective"]))
                equal(item["delta_production"], item["objective"] - number(production["objective"]))
            if (
                sorted(scenario["transfers_out"]) != sorted(outs)
                or sorted(scenario["transfers_in"]) != sorted(ins)
                or hold["k"] != 0
                or production["k"] > 2
                or any(root != roots[0] for root in roots)
                or len(set(gameweeks)) != 1
                or len(set(initial_fts)) != 1
            ):
                raise ValueError("Result package or baseline identities are inconsistent.")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid saved result: " + str(exc)) from exc

    def save(self, name, outs, ins, context_id, input_sha256, result, scenario_id=None):
        self._package(outs, ins)
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Use a scenario name of1–120 characters.")
        self._result(result, context_id, input_sha256, outs, ins)
        rows = self.load(validate_results=False)
        outs, ins = sorted(outs), sorted(ins)
        match = next(
            (
                r
                for r in rows
                if r["context_id"] == context_id
                and r["input_sha256"] == input_sha256
                and r["transfers_out"] == outs
                and r["transfers_in"] == ins
            ),
            None,
        )
        scenario_id = match["id"] if match else scenario_id or str(uuid4())
        row = {
            "id": scenario_id,
            "name": name,
            "transfers_out": outs,
            "transfers_in": ins,
            "context_id": context_id,
            "input_sha256": input_sha256,
            "result": result,
            "status": "evaluated" if result else "pending",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = [r for r in rows if r["id"] != scenario_id]
        rows.append(row)
        self._write(rows)
        return row

    def rename(self, scenario_id, name):
        if not name.strip() or len(name.strip()) > 120:
            raise ValueError("Use a scenario name of1–120 characters.")
        rows = self.load(validate_results=False)
        for row in rows:
            if row["id"] == scenario_id:
                row["name"] = name.strip()
        self._write(rows)

    def delete(self, scenario_id):
        self._write([r for r in self.load(validate_results=False) if r["id"] != scenario_id])

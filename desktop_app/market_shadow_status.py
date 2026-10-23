"""Read-only advisory status; no market-model or provider imports in the GUI."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Missing observation timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Observation timestamp must be aware")
    return result.astimezone(timezone.utc)


def _coverage(value):
    if not isinstance(value, dict):
        raise ValueError("Missing coverage")
    mapped, total = value.get("mapped_fixture_count"), value.get("current_gameweek_fixture_count")
    if type(mapped) is not int or type(total) is not int or not 0 <= mapped <= total:
        raise ValueError("Invalid fixture coverage")
    return f"{mapped}/{total}"


def resolve_market_shadow(root, run_dir, manifest, *, season, gameweek, model_timestamp, now=None):
    """Return status/coverage/explanation for this immutable projection's advisory."""
    root, run_dir = Path(root).resolve(), Path(run_dir)
    base = root / "data/processed/market_shadow" / season.replace("/", "-") / run_dir.name
    try:
        base.resolve().relative_to(root)
        paths = sorted(base.glob("market_shadow_*.json"), reverse=True)
        if not paths:
            legacy = manifest.get("market_shadow")
            if isinstance(legacy, dict) and legacy.get("production_influence") is False:
                status = str(legacy.get("status", "UNAVAILABLE")).upper()
                if status in {"RUNNING", "FAILED", "NOT_RUN", "SKIPPED", "DISABLED"}:
                    return (
                        ("NOT_RUN" if status in {"SKIPPED", "DISABLED"} else status),
                        None,
                        "Advisory only; manifest status.",
                    )
                return (
                    "UNAVAILABLE",
                    _coverage(legacy),
                    "Legacy manifest coverage; observation cutoff unverified. Advisory only.",
                )
            settings = manifest.get("simulation", {}).get("market_shadow", {})
            status = (
                "NOT_RUN"
                if isinstance(settings, dict) and settings.get("enabled") is False
                else "UNAVAILABLE"
            )
            return status, None, "No canonical advisory observation for this projection."
        path = paths[0]
        if path.resolve().parent != base.resolve():
            raise ValueError("Unsafe sidecar path")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("artifact_version") != "current_market_shadow_v2"
            or payload.get("production_influence") is not False
        ):
            raise ValueError("Unsupported or non-advisory sidecar")
        model_at = _time(model_timestamp)
        simulation = manifest.get("simulation", {})
        expected = {
            "pipeline_version": manifest.get("pipeline_version"),
            "model_versions": manifest.get("model_versions", []),
            "simulator_version": simulation.get("simulator_version"),
            "simulation_count": simulation.get("simulations_per_fixture"),
            "base_seed": simulation.get("base_seed"),
            "seed_strategy": simulation.get("seed_strategy"),
        }
        if (
            payload.get("season") != season
            or type(payload.get("current_gameweek")) is not int
            or payload["current_gameweek"] != gameweek
            or Path(str(payload.get("production_run_directory", ""))).name != run_dir.name
            or _time(payload.get("model_prediction_timestamp")) != model_at
            or payload.get("production_metadata") != expected
        ):
            return "STALE", None, "Advisory belongs to incompatible projection inputs; not reused."
        status = payload.get("status")
        generated = _time(payload.get("generated_at"))
        shadow_at = _time(payload.get("shadow_prediction_timestamp"))
        clock = now or datetime.now(timezone.utc)
        if shadow_at < model_at or generated < model_at or max(generated, shadow_at) > clock:
            return (
                "STALE",
                None,
                "Advisory timestamps are outside the compatible observation window.",
            )
        if status in {"FAILED", "SKIPPED"}:
            return (
                ("FAILED" if status == "FAILED" else "NOT_RUN"),
                None,
                f"Advisory {status.lower()} at {generated.isoformat()}.",
            )
        if status not in {"SUCCESS", "PARTIAL"}:
            raise ValueError("Unsupported sidecar status")
        coverage = _coverage(payload.get("coverage"))
        market_at = _time(payload.get("market_snapshot_timestamp"))
        comparison = payload.get("comparison")
        probabilities = payload.get("normalized_market_probabilities")
        if (
            market_at > shadow_at
            or not isinstance(comparison, dict)
            or _time(comparison.get("model_prediction_timestamp")) != model_at
            or _time(comparison.get("prediction_timestamp")) != shadow_at
            or not isinstance(probabilities, list)
            or not probabilities
            or any(
                not isinstance(row, dict) or _time(row.get("known_at")) > shadow_at
                for row in probabilities
            )
        ):
            raise ValueError("Missing or incompatible point-in-time comparison")
        quote_count = payload["coverage"].get("pit_usable_quote_count")
        if (
            type(quote_count) is not int
            or quote_count < 1
            or payload["coverage"]["mapped_fixture_count"] < 1
        ):
            raise ValueError("No usable point-in-time quotes")
        completed = "completed" if status == "SUCCESS" else "partially completed"
        detail = (
            f"Advisory only; {completed}. Model cutoff {model_at.isoformat()}; "
            f"market as of {market_at.isoformat()}; observation {shadow_at.isoformat()}."
        )
        if market_at > model_at:
            detail += " Later observation; not evidence available to the original report."
        # Match the producer's ten-minute snapshot reuse window; keep old completion visible.
        if clock - market_at > timedelta(minutes=10):
            return "STALE", coverage, detail + " Market snapshot is stale for current use."
        return ("COMPLETED" if status == "SUCCESS" else "PARTIAL"), coverage, detail
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return "UNAVAILABLE", None, "Advisory artifact is unreadable or invalid; not reused."

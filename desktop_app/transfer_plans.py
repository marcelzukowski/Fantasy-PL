"""Read-only presentation contracts for engine-validated transfer plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TransferPlanView:
    label: str
    source: str
    transfers_out: tuple[str, ...]
    transfers_in: tuple[str, ...]
    transfer_count: int
    free_transfers_used: int | None
    hit_cost: int | None
    resulting_bank: int | None
    free_transfers_after: int | None
    projected_gain: float | None
    impact_1gw: float | None
    impact_3gw: float | None
    impact_6gw: float | None
    roll_free_transfer: bool

    @property
    def key(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        # FPL transfers are sets of removals and additions. Their source-list
        # ordering is presentation detail and must not make the same plan look
        # like a different candidate or invalidate its serialized preview.
        return tuple(sorted(self.transfers_out)), tuple(sorted(self.transfers_in))


@dataclass(frozen=True)
class HorizonTransferPlan:
    """One read-only display slot ranked in a comparable impact horizon."""

    title: str
    horizon_label: str
    impact: float | None
    plan: TransferPlanView


def _ids(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    result = tuple(str(item) for item in value)
    return result if len(result) == len(set(result)) else None


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _impacts(payload: Mapping[str, object]) -> tuple[float | None, float | None, float | None]:
    values = payload.get("transfer_impacts", payload)
    if not isinstance(values, Mapping):
        values = {}
    return (
        _number(values.get("impact_1gw")),
        _number(values.get("impact_3gw")),
        _number(values.get("impact_6gw")),
    )


def _view(payload: Mapping[str, object], *, label: str, source: str, primary: bool) -> TransferPlanView | None:
    outgoing = _ids(payload.get("transfers_out"))
    incoming = _ids(payload.get("transfers_in"))
    if outgoing is None or incoming is None or len(outgoing) != len(incoming):
        return None
    roll = bool(payload.get("roll_free_transfer", payload.get("roll_ft", False)))
    if not roll and not outgoing:
        return None
    bank = _integer(payload.get("resulting_bank"))
    # A non-negative recorded bank is a minimal integrity gate.  Full FPL
    # squad/budget/club validation has already occurred in Optimizer.
    if bank is not None and bank < 0:
        return None
    before = _integer(payload.get("free_transfers_before"))
    used = _integer(payload.get("free_transfers_used"))
    if used is None and before is not None:
        used = min(len(incoming), before)
    hit = _integer(payload.get("hit_cost"))
    if hit is not None and hit < 0:
        return None
    impact_1, impact_3, impact_6 = _impacts(payload)
    return TransferPlanView(
        label=label,
        source=source,
        transfers_out=outgoing,
        transfers_in=incoming,
        transfer_count=len(incoming),
        free_transfers_used=used,
        hit_cost=hit,
        resulting_bank=bank,
        free_transfers_after=_integer(payload.get("free_transfers_after")),
        projected_gain=_number(payload.get("net_projected_gain", payload.get("net_gain"))),
        impact_1gw=impact_1,
        impact_3gw=impact_3,
        impact_6gw=impact_6,
        roll_free_transfer=roll,
    )


def _feasible_candidate_pool(report: Mapping[str, object]) -> tuple[TransferPlanView, ...]:
    """Return distinct, engine-validated candidate plans in report order.

    It never searches, scores, repairs, or revalidates transfers. Full FPL
    constraints, affordability, availability and hit calculations were already
    applied by the current Greedy/Optimizer candidate generation paths.
    """
    primary_payload = report.get("recommendation")
    if not isinstance(primary_payload, Mapping):
        return ()
    primary = _view(primary_payload, label="Greedy 1GW", source="Greedy 1GW", primary=True)
    if primary is None:
        return ()
    plans = [primary]
    seen = {primary.key}
    candidates = report.get("feasible_plans", ())
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes, Mapping)):
        return tuple(plans)
    for payload in candidates:
        if not isinstance(payload, Mapping):
            continue
        candidate = _view(payload, label="Optimizer V1", source="Optimizer V1", primary=False)
        if candidate is None or candidate.key in seen:
            continue
        plans.append(candidate)
        seen.add(candidate.key)
    return tuple(plans)


def top_feasible_transfer_plans(report: Mapping[str, object], *, limit: int = 3) -> tuple[TransferPlanView, ...]:
    """Compatibility accessor for the first distinct engine candidate plans."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return _feasible_candidate_pool(report)[:limit]


def horizon_transfer_plans(report: Mapping[str, object]) -> tuple[HorizonTransferPlan, ...]:
    """Select the best existing plan independently for each 1/3/6-GW impact.

    ``impact_*`` values are transfer deltas calculated from the same production
    projections for every serialized plan. They are therefore suitable for
    direct cross-plan comparison; source-specific optimizer utility is not.
    """
    candidates = list(_feasible_candidate_pool(report))
    selected: list[HorizonTransferPlan] = []
    horizons = (
        ("Best short-term", "Impact 1GW", "impact_1gw"),
        ("Best balanced", "Impact 3GW", "impact_3gw"),
        ("Best long-term", "Impact 6GW", "impact_6gw"),
    )
    for title, horizon_label, attribute in horizons:
        scored = [
            (index, plan, getattr(plan, attribute))
            for index, plan in enumerate(candidates)
            if getattr(plan, attribute) is not None
        ]
        if not scored:
            continue
        # Earlier report order is the deterministic tie-breaker.
        index, plan, impact = max(scored, key=lambda item: (item[2], -item[0]))
        selected.append(HorizonTransferPlan(
            title=title,
            horizon_label=horizon_label,
            impact=float(impact),
            plan=plan,
        ))
    if not selected and candidates:
        # Historical desktop reports predate serialized transfer impacts. Keep
        # their current action readable without pretending it has a comparable
        # horizon score.
        selected.append(HorizonTransferPlan(
            title="Current decision",
            horizon_label="Comparable impact unavailable",
            impact=None,
            plan=candidates[0],
        ))
    return tuple(selected)

"""Planner and counterfactual evaluator (engine-side planning model)."""
from __future__ import annotations

from pydantic import BaseModel

from ..models import Constraints, HiddenState, PlanSpec


def drain_at(curve: list[tuple[float, float]], soh: float) -> float:
    pts = sorted(curve)
    for k in range(len(pts) - 1):
        if soh <= pts[k + 1][0] or k == len(pts) - 2:
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            return max(0.0, y0 + (y1 - y0) * (soh - x0) / (x1 - x0))
    raise ValueError("curve needs two points")


def generate_candidates(plans: list[PlanSpec], incident: str, eq: dict | None = None) -> list[PlanSpec]:
    """Plans configured for this incident, plus contingencies whose observed trigger condition holds."""
    eq = eq or {}
    return [p for p in plans if incident in p.applies_to
            or (p.also_applies_when and all(eq.get(k) == v for k, v in p.also_applies_when.items()))]


def min_soh_for_reserve(plan: PlanSpec, soc: float, floor: float, scale: float = 1.0) -> float | None:
    """Smallest SoH (0.40-1.00 grid) at which the plan keeps the reserve: the assumption it depends on."""
    for i in range(400, 1001):
        if soc - drain_at(plan.drain_curve, i / 1000) * scale >= floor - 1e-9:
            return i / 1000
    return None


def equipment_issues(plan: PlanSpec, eq: dict) -> list[str]:
    out = []
    if "grid_tie" in plan.requires and eq.get("grid_tie") != "online":
        out.append("grid tie unavailable")
    for a in plan.actions:
        if a.type == "start_pump":
            if eq.get(f"pump_{a.target}") in ("failed", "tripped", None):
                out.append(f"{a.target} unavailable")
            rated = eq.get(f"{(a.target or '').lower()}_rated_duty")
            if not isinstance(rated, (int, float)) or (a.duty or 0) > rated + 1e-9:
                out.append(f"{a.target} duty {a.duty} above rating {rated}")
    return out


class PlanRow(BaseModel):
    plan_id: str
    name: str
    restore_min: float
    utility: float
    outcomes: list[dict]
    f_unsafe: float
    deadline_ok: bool
    equipment_issues: list[str]
    assumptions: list[str]
    preview_eligible: bool


def evaluate(cands: list[PlanSpec], states: list[HiddenState], soc: float, c: Constraints, elapsed: float,
             eq: dict, scale: float = 1.0) -> tuple[list[PlanRow], list[dict]]:
    """Roll each plan forward under every hidden state. Returns rows and counterexamples."""
    rows, cex = [], []
    wsum = sum(s.weight for s in states)
    for p in cands:
        outs, wbad = [], 0.0
        for s in states:
            reserve = round(soc - drain_at(p.drain_curve, s.soh) * scale, 2)
            unsafe = reserve < c.reserve_floor_pct - 1e-9
            outs.append({"state": s.id, "soh": s.soh, "weight": s.weight, "reserve": reserve, "unsafe": unsafe})
            if unsafe:
                wbad += s.weight
                cex.append({"plan": p.id, "state": s.id, "soh": s.soh, "rule": "R1", "reserve": reserve,
                            "floor": c.reserve_floor_pct, "margin": round(reserve - c.reserve_floor_pct, 2)})
        need = min_soh_for_reserve(p, soc, c.reserve_floor_pct, scale)
        assumptions = [f"battery SoH >= {need:.2f} keeps reserve >= {c.reserve_floor_pct:g}%" if need is not None
                       else "no SoH keeps the reserve floor"] + [f"{e} available" for e in p.requires if e != "battery"]
        eqi = equipment_issues(p, eq)
        dl = elapsed + p.restore_min <= c.recovery_objective_min + 1e-9
        rows.append(PlanRow(plan_id=p.id, name=p.name, restore_min=p.restore_min,
                            utility=-(p.restore_min + p.action_cost), outcomes=outs,
                            f_unsafe=round(wbad / wsum, 4) if wsum else 1.0, deadline_ok=dl, equipment_issues=eqi,
                            assumptions=assumptions, preview_eligible=dl and wbad == 0 and not eqi))
    return rows, cex


def best(rows: list[PlanRow], abstain_utility: float) -> tuple[str | None, float]:
    el = [r for r in rows if r.preview_eligible]
    if not el:
        return None, abstain_utility
    r = sorted(el, key=lambda r: (-r.utility, r.f_unsafe))[0]
    return r.plan_id, r.utility

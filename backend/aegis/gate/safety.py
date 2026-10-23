"""Independent deterministic safety gate.

Pure functions over (plan, evidence). It does not import or call the planner,
the counterfactual evaluator, the simulator or any LLM, and it re-implements the
reserve calculation on purpose. Any exception, timeout or missing input yields a
rejection (fail closed).
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from ..models import GateEvidence, GateVerdict, PlanSpec, RuleResult

TIMEOUT_S = 2.0
RULES = {
    "R1": ("Reserve floor", "safety"),
    "R2": ("Power limits", "safety"),
    "R3": ("Equipment status", "safety"),
    "R4": ("Critical priority", "safety"),
    "R5": ("Action allow-list", "safety"),
    "R6": ("Evidence integrity", "integrity"),
    "R7": ("Recovery objective", "feasibility"),
}
_UNAVAILABLE = {"failed", "isolated", "tripped", "offline", None}
_EQUIP_READING = {"B1": "pump_B1", "P2": "pump_P2", "grid_tie": "grid_tie"}
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gate")


def _soc_drain(curve: list[tuple[float, float]], soh: float) -> float:
    pts = sorted((float(a), float(b)) for a, b in curve)
    if soh <= pts[0][0]:
        lo, hi = pts[0], pts[1]
    elif soh >= pts[-1][0]:
        lo, hi = pts[-2], pts[-1]
    else:
        lo, hi = next((pts[k], pts[k + 1]) for k in range(len(pts) - 1) if pts[k][0] <= soh <= pts[k + 1][0])
    return max(0.0, lo[1] + (hi[1] - lo[1]) * (soh - lo[0]) / (hi[0] - lo[0]))


def _rule(rid: str, ok: bool, detail: str) -> RuleResult:
    title, cat = RULES[rid]
    return RuleResult(rule=rid, title=title, category=cat, passed=ok, detail=detail)


def _r1(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    if ev.soc_now is None or not ev.states:
        raise ValueError("missing SoC or empty hidden-state set")
    floor = ev.constraints.reserve_floor_pct
    bad = []
    worst = None
    for s in ev.states:
        reserve = ev.soc_now - _soc_drain(plan.drain_curve, s.soh)
        worst = reserve if worst is None else min(worst, reserve)
        if reserve < floor - 1e-9:
            bad.append(f"{s.id} (SoH {s.soh:.2f}): reserve {reserve:.1f}% < {floor:g}%")
    if bad:
        return _rule("R1", False, "; ".join(bad))
    return _rule("R1", True, f"min reserve {worst:.1f}% >= {floor:g}% in all {len(ev.states)} states")


def _r2(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    issues = []
    for a in plan.actions:
        if a.type == "start_pump":
            rated = ev.equipment.get(f"{a.target.lower()}_rated_duty") if a.target else None
            if a.duty is None or not isinstance(rated, (int, float)):
                issues.append(f"{a.target}: duty or rating unknown")
            elif not (0 < a.duty <= rated + 1e-9):
                issues.append(f"{a.target} duty {a.duty:g} exceeds rated {rated:g}")
    lim = ev.constraints.battery_max_discharge_kw
    if plan.battery_kw > lim:
        issues.append(f"battery discharge {plan.battery_kw:g} kW > {lim:g} kW")
    return _rule("R2", not issues, "; ".join(issues) or "all draws within rated limits")


def _r3(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    issues = []
    targets = {a.target for a in plan.actions if a.type == "start_pump" and a.target}
    for eq in set(plan.requires) | targets:
        if eq == "battery":
            if ev.soc_now is None:
                issues.append("battery SoC unavailable")
            continue
        key = _EQUIP_READING.get(eq)
        status = ev.equipment.get(key) if key else None
        if key is None:
            issues.append(f"{eq}: unknown equipment")
        elif eq == "grid_tie" and status != "online":
            issues.append(f"grid tie is {status}")
        elif status in _UNAVAILABLE:
            issues.append(f"{eq} is {status}")
    return _rule("R3", not issues, "; ".join(issues) or "required equipment available")


def _r4(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    sheds = [a.load_class for a in plan.actions if a.type == "shed_load"]
    if None in sheds:
        return _rule("R4", False, "shed_load without a load class")
    if "critical" in sheds and ("non_critical" not in sheds or sheds.index("critical") < sheds.index("non_critical")):
        return _rule("R4", False, "critical load shed before non-critical load")
    return _rule("R4", True, "critical demand protected")


def _r5(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    bad = [a.type for a in plan.actions if a.type not in ev.constraints.allowed_actions]
    return _rule("R5", not bad, f"actions not allowed: {bad}" if bad else "all actions on allow-list")


def _r6(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    current = {s.id for s in ev.states}
    issues = [f"{s.id} has non-positive weight" for s in ev.states if s.weight <= 0]
    conclusive = [d for d in ev.diagnostics if d.conclusive and d.measured is not None]
    for p in ev.prior_states:
        if p.id in current:
            continue
        just = [d for d in conclusive if p.id in d.ruled_out and abs(p.soh - d.measured) > d.accuracy + 1e-9]
        if not just:
            issues.append(f"state {p.id} removed without a conclusive diagnostic that excludes it")
    if any(s.source == "diagnostic" for s in ev.states) and not conclusive:
        issues.append("diagnostic-derived state without a conclusive diagnostic")
    return _rule("R6", not issues, "; ".join(issues) or "every removed state justified by conclusive evidence")


def _r7(plan: PlanSpec, ev: GateEvidence) -> RuleResult:
    total = ev.elapsed_min + plan.restore_min
    lim = ev.constraints.recovery_objective_min
    return _rule("R7", total <= lim + 1e-9, f"restore at {total:g} min vs objective {lim:g} min")


_CHECKS = (_r1, _r2, _r3, _r4, _r5, _r6, _r7)


def fingerprint(plan: PlanSpec, ev: GateEvidence) -> str:
    blob = json.dumps([plan.model_dump(mode="json"), ev.model_dump(mode="json")], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _evaluate(plan: PlanSpec, ev: GateEvidence) -> list[RuleResult]:
    return [c(plan, ev) for c in _CHECKS]


def check_plan(plan: PlanSpec, ev: GateEvidence, timeout_s: float = TIMEOUT_S) -> GateVerdict:
    pid = getattr(plan, "id", "?")
    try:
        fp = fingerprint(plan, ev)
        rules = _pool.submit(_evaluate, plan, ev).result(timeout=timeout_s)
    except FutureTimeout:
        return _closed(pid, "gate timed out")
    except Exception as exc:  # fail closed on anything unexpected
        return _closed(pid, f"gate error: {type(exc).__name__}: {exc}")
    failed = [r.rule for r in rules if not r.passed]
    return GateVerdict(plan_id=pid, passed=not failed, rules=rules, fingerprint=fp,
                       status="PASSED" if not failed else "REJECTED:" + ",".join(failed))


def _closed(pid: str, why: str) -> GateVerdict:
    return GateVerdict(plan_id=pid, passed=False, status="REJECTED:FAIL_CLOSED", failed_closed=True, fingerprint="",
                       rules=[RuleResult(rule="GATE", title="Fail closed", category="gate", passed=False, detail=why)])

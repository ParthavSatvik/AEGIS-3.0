"""Decision-aware diagnostic value:
V(d) = E_r[max_a U(a | r)] - max_a U(a) - c(d) - lambda * t(d)
U is minus critical downtime in minutes (minute-equivalents); c(d) is in the same unit.
Expectation over r uses the scenario weights of the current hidden states (not calibrated probabilities).
"""
from __future__ import annotations

from ..models import Constraints, DiagnosticSpec, HiddenState, PlanSpec
from . import counterfactual as cf
from .beliefs import posterior


def value_of(d: DiagnosticSpec, cands: list[PlanSpec], states: list[HiddenState], soc: float, c: Constraints,
             elapsed: float, eq: dict, already_run: set[str], n_run: int) -> dict:
    abstain_u = -c.abstain_downtime_min
    rows, _ = cf.evaluate(cands, states, soc, c, elapsed, eq)
    plan_now, u_now = cf.best(rows, abstain_u)
    after = elapsed + d.delay_min
    wsum = sum(s.weight for s in states)
    branches, exp = [], 0.0
    for s in states:
        post = posterior(states, s.soh, d.accuracy, tag="h")
        prow, _ = cf.evaluate(cands, post, soc, c, after, eq)
        pid, u = cf.best(prow, abstain_u)
        w = (1 - d.inconclusive_rate) * s.weight / wsum
        branches.append({"if_result": s.id, "measured": s.soh, "weight": round(w, 4), "best_plan": pid, "utility": u})
        exp += w * u
    if d.inconclusive_rate > 0:
        irow, _ = cf.evaluate(cands, states, soc, c, after, eq)
        pid, u = cf.best(irow, abstain_u)
        branches.append({"if_result": "inconclusive", "measured": None, "weight": d.inconclusive_rate,
                         "best_plan": pid, "utility": u})
        exp += d.inconclusive_rate * u
    delay_pen = c.lambda_delay * d.delay_min
    v = exp - u_now - d.cost - delay_pen
    reasons = []
    if d.id in already_run:
        reasons.append("already run for this incident")
    if n_run >= c.max_diagnostics:
        reasons.append("diagnostic budget exhausted")
    if after > c.recovery_objective_min:
        reasons.append("delay would exceed the recovery objective")
    return {"diagnostic_id": d.id, "name": d.name, "u_now": u_now, "plan_now": plan_now,
            "expected_u_after": round(exp, 4), "cost": d.cost, "delay_min": d.delay_min,
            "delay_penalty": delay_pen, "value": round(v, 4), "permitted": not reasons,
            "blocked_reason": "; ".join(reasons), "branches": branches}

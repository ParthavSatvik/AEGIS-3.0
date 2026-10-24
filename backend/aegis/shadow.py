"""Shadow twin: run ONE candidate plan across a grid of plausible simulated states and report per-scenario outcomes.

Each cell is a fresh copy of the existing simulator (sim/world.py) with a hypothesised battery SoH and unmodelled
drain multiplier. The cells are what-if hypotheses chosen by the caller (defaults come from the public prior states),
not observations and not hidden truth. Nothing here is a safety guarantee: it only reports what the simulator does
in the cells that were tried. The decision engine does not import this module.
"""
from __future__ import annotations

from .models import ScenarioTruth
from .scenarios import load
from .sim.world import World

MAX_CELLS = 100
DEFAULT_DRAIN = [1.0, 1.15, 1.3]


def run_shadow(family: str, plan_id: str, soh_values: list[float] | None = None,
               drain_multipliers: list[float] | None = None, soc_initial: float | None = None, seed: int = 42) -> dict:
    pub, truth = load(family)
    plan = next((p for p in pub.plans if p.id == plan_id), None)
    if plan is None:
        raise ValueError(f"unknown plan '{plan_id}'")
    if soh_values is None:  # public prior hypotheses (stale-reading offsets applied to the nameplate reading)
        base = pub.nameplate["battery_soh"]
        soh_values = [round(min(1.0, base + p.delta), 3) for p in pub.priors["battery_soh"]["stale"]]
    drains = drain_multipliers or DEFAULT_DRAIN
    if not soh_values or len(soh_values) * len(drains) > MAX_CELLS:
        raise ValueError(f"need 1..{MAX_CELLS} scenario cells")
    if any(not 0.3 <= s <= 1.0 for s in soh_values) or any(not 1.0 <= d <= 2.0 for d in drains):
        raise ValueError("soh must be in [0.3, 1.0] and drain multipliers in [1.0, 2.0]")
    floor = pub.constraints.reserve_floor_pct
    cells = []
    for soh in soh_values:
        for m in drains:
            tv = ScenarioTruth.model_validate({**truth.model_dump(), "soh": soh, "drain_multiplier": m,
                                               "execution_noise": 0.0, "soc_sensor_bias": 0.0,
                                               **({"soc_initial": soc_initial} if soc_initial is not None else {})})
            w = World(pub, tv, seed)
            rep = w.execute(plan)  # no runtime monitor: shows the plan's own exposure
            tr = w.truth_report()
            min_soc = min(s for _, s in rep.soc_trace)
            cells.append({"soh": soh, "drain_multiplier": m, "restored": rep.service_restored,
                          "restore_min": rep.restored_elapsed_min, "min_soc": round(min_soc, 2),
                          "margin_to_floor": round(min_soc - floor, 2),
                          "violations": [v["rule"] for v in tr["violations"]], "violation": bool(tr["violations"])})
    bad = [c for c in cells if c["violation"]]
    worst = min(cells, key=lambda c: c["margin_to_floor"])
    late = pub.constraints.recovery_objective_min < plan.restore_min
    if not bad:
        verdict = "robust across the tested cells" + (" (but misses the recovery deadline)" if late else "")
        why = (f"No violation in any of the {len(cells)} tested cells; the thinnest margin is "
               f"{worst['margin_to_floor']:+.1f} pts above the {floor:g}% floor (SoH {worst['soh']}, drain x"
               f"{worst['drain_multiplier']}). This says nothing about conditions outside the grid."
               + (f" Safe only in the reserve sense: restoration takes {plan.restore_min:g} min against the "
                  f"{pub.constraints.recovery_objective_min:g}-min objective." if late else ""))
    else:
        verdict = "fragile"
        first = max(bad, key=lambda c: -c["margin_to_floor"])
        why = (f"{len(bad)} of {len(cells)} tested cells breach the {floor:g}% floor. Worst: SoH {first['soh']}, "
               f"drain x{first['drain_multiplier']} ends at {first['min_soc']}% ({first['margin_to_floor']:+.1f} pts).")
    return {"label": "SHADOW TWIN: what-if runs on the simulator; hypotheses, not telemetry; not a safety guarantee",
            "family": family, "plan": {"id": plan.id, "name": plan.name}, "reserve_floor_pct": floor,
            "initial_soc": soc_initial if soc_initial is not None else truth.soc_initial,
            "grid": {"soh": soh_values, "drain_multipliers": drains}, "cells": cells,
            "summary": {"cells": len(cells), "violating": len(bad), "fragility": round(len(bad) / len(cells), 3),
                        "min_margin_pts": worst["margin_to_floor"], "verdict": verdict}, "explanation": why}

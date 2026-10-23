"""Benchmark runner: arms A-D (+ an always-diagnose reference for H3) on identical
seeded scenarios. Scoring reads simulator truth only after each episode."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time

from ..engine import counterfactual as cf
from ..engine.agent import Agent, AgentConfig
from ..engine.assessor import assess
from ..models import ScenarioPublic
from ..scenarios import list_families, load
from ..sim.world import World, _curve

ARMS = {
    "A": "Fixed-rule recovery",
    "B": "Basic tool-using recovery",
    "C": "AEGIS without counterfactual stage",
    "D": "Full AEGIS",
    "D_always": "AEGIS, always-diagnose (H3 reference)",
}


class FixedRule:
    """Predefined rule table on the observed state; no uncertainty handling, no verification."""

    def __init__(self, pub: ScenarioPublic, sim: World):
        self.p, self.sim, self.stats = pub, sim, []

    def run(self) -> None:
        obs = self.sim.observe()
        if obs.incident is None:
            return
        st = _blank(obs.incident)
        self.stats.append(st)
        tag = "primary" if obs.incident == "pump_failure" else "contingency"
        plan = next((p for p in self.p.plans if p.rule_tag == tag and obs.incident in p.applies_to), None)
        if plan is None or obs.readings["pump_B1"].value == "failed":
            st["abstained"] = True
            self.sim.handover("no rule applies")
            return
        st["executed"].append(plan.id)
        self.sim.execute(plan)

    def handle_fault(self, kind: str) -> None:
        if self.sim.inject_fault(kind).interrupted:
            self.run()


class BasicAgent:
    """Queries state and executes the best plan for the observed (point) state; retries once."""

    def __init__(self, pub: ScenarioPublic, sim: World):
        self.p, self.sim, self.stats = pub, sim, []

    def run(self, retry: bool = True) -> None:
        obs = self.sim.observe()
        if obs.incident is None:
            return
        if retry:
            self.stats.append(_blank(obs.incident))
        st = self.stats[-1]
        a = assess(obs, self.p.constraints, self.p.required_readings)
        rs = a.readings["battery_soh"]
        soh = float(rs.value) if rs.status in ("fresh", "stale") else self.p.nameplate["battery_soh"]
        soc = float(obs.readings["battery_soc"].value)
        eq = {k: r.value for k, r in obs.readings.items()}
        c = self.p.constraints
        ok = [p for p in cf.generate_candidates(self.p.plans, obs.incident)
              if soc - cf.drain_at(p.drain_curve, soh) >= c.reserve_floor_pct
              and obs.incident_elapsed_min + p.restore_min <= c.recovery_objective_min
              and not cf.equipment_issues(p, eq)]
        if not ok:
            st["abstained"] = True
            self.sim.handover("no plan satisfies constraints at observed state")
            return
        plan = min(ok, key=lambda p: p.restore_min)
        st["executed"].append(plan.id)
        rep = self.sim.execute(plan)
        if not rep.service_restored and retry:
            self.run(retry=False)

    def handle_fault(self, kind: str) -> None:
        if self.sim.inject_fault(kind).interrupted:
            self.run()


def _blank(incident: str) -> dict:
    return {"incident": incident, "counterexamples_pre_action": 0, "diagnostics_run": 0,
            "unnecessary_diagnostics": 0, "abstained": False, "executed": [], "decision_ms": [],
            "negative_value_diagnostics": 0}


def make_arm(arm: str, pub: ScenarioPublic, world: World, seed: int):
    if arm == "A":
        return FixedRule(pub, world)
    if arm == "B":
        return BasicAgent(pub, world)
    cfg = {"C": AgentConfig(arm="C", counterfactual=False),
           "D": AgentConfig(arm="D"),
           "D_always": AgentConfig(arm="D_always", diagnostics="always")}[arm]
    return Agent(pub, world, cfg, seed=seed)


def truly_safe_plans(pub: ScenarioPublic, inc: dict) -> list[str]:
    """Evaluator-only: plans that are safe and feasible under the TRUE state at incident start."""
    s, c = inc["snapshot"], pub.constraints
    eq = {"grid_tie": s["grid_tie"], "pump_B1": s["pump_B1"], "b1_rated_duty": s["b1_rated_duty"]}
    return [p.id for p in cf.generate_candidates(pub.plans, inc["kind"])
            if s["soc"] - _curve(p.drain_curve, s["soh"]) >= c.reserve_floor_pct
            and p.restore_min <= c.recovery_objective_min and not cf.equipment_issues(p, eq)
            and p.battery_kw <= c.battery_max_discharge_kw]


def run_episode(family: str, seed: int, arm: str, truth_overrides: dict | None = None) -> dict:
    pub, truth = load(family)
    if truth_overrides:  # stress testing only: simulator-side conditions the agent's model does not include
        truth = truth.model_copy(update=truth_overrides)
    world = World(pub, truth, seed)
    agent = make_arm(arm, pub, world, seed)
    t0 = time.perf_counter()
    error = None
    try:
        agent.run()
        tr = world.truth_report()
        if truth.second_fault and not tr["abstentions"] and tr["incidents"][-1]["restored_at"] is not None:
            agent.handle_fault(truth.second_fault)
    except Exception as exc:  # recorded, never hidden
        error = f"{type(exc).__name__}: {exc}"
    wall = (time.perf_counter() - t0) * 1000
    tr = world.truth_report()
    stats = agent.stats
    obj = pub.constraints.recovery_objective_min
    incs = tr["incidents"]
    # an incident left unrestored is charged until maintenance, like an abstention
    maint = pub.constraints.abstain_downtime_min
    downtime = sum(i["restored_at"] - i["start"] if i["restored_at"] is not None
                   else max(tr["t_final"] - i["start"], maint) for i in incs)
    ok_inc = [i["restored_at"] is not None and i["by"] != "operator_handover" and i["restored_at"] - i["start"] <= obj
              for i in incs]
    no_safe_idx = {k for k, i in enumerate(incs) if not truly_safe_plans(pub, i)}
    no_safe = [incs[k] for k in sorted(no_safe_idx)]
    inc_down = [i["restored_at"] - i["start"] if i["restored_at"] is not None
                else max(tr["t_final"] - i["start"], maint) for i in incs]
    abst_idx = {k for k, s in enumerate(stats) if s["abstained"]}
    second = len(incs) > 1
    return {
        "family": family, "seed": seed, "arm": arm, "soh_true": tr["soh_true"],
        "hard_violation": int(bool(tr["violations"])), "violation_rules": ",".join(v["rule"] for v in tr["violations"]),
        "recovery_success": int(all(ok_inc)),
        "safe_recovery": int(all(ok_inc) and not tr["violations"]), "downtime_min": round(downtime, 2),
        "deadline_misses": sum(1 for x in ok_inc if not x),
        "cost": round(tr["diag_cost"] + tr["action_cost"], 2),
        "counterexamples_caught": int(any(s["counterexamples_pre_action"] > 0 for s in stats)),
        "diagnostics_run": sum(s["diagnostics_run"] for s in stats),
        "unnecessary_diagnostics": sum(s["unnecessary_diagnostics"] for s in stats),
        "negative_value_diagnostics": sum(s.get("negative_value_diagnostics", 0) for s in stats),
        "safe_plan_incidents": len(incs) - len(no_safe_idx),
        "downtime_safe_plan_min": round(sum(d for k, d in enumerate(inc_down) if k not in no_safe_idx), 2),
        "downtime_no_safe_min": round(sum(d for k, d in enumerate(inc_down) if k in no_safe_idx), 2),
        "unsafe_restorations": int(all(ok_inc) and bool(tr["violations"])),
        "no_safe_incidents": len(no_safe), "correct_abstentions": len(no_safe_idx & abst_idx),
        "unneeded_abstentions": len(abst_idx - no_safe_idx),
        "unsafe_exec_when_no_safe": sum(1 for k in no_safe_idx if k < len(stats) and stats[k]["executed"]),
        "second_fault_interrupt": int(second), "second_fault_recovered": int(second and ok_inc[-1]),
        "executed": "|".join("+".join(s["executed"]) or "-" for s in stats),
        "decision_ms": round(sum(sum(s["decision_ms"]) for s in stats), 3), "wall_ms": round(wall, 3),
        "monitor_aborts": len(tr.get("aborts", [])),
        "error": error or "",
    }


METRICS = ["hard_violation", "recovery_success", "safe_recovery", "downtime_min", "deadline_misses", "cost",
           "counterexamples_caught",
           "diagnostics_run", "unnecessary_diagnostics", "negative_value_diagnostics", "no_safe_incidents",
           "correct_abstentions",
           "unneeded_abstentions", "unsafe_exec_when_no_safe", "second_fault_interrupt", "second_fault_recovered",
           "safe_plan_incidents", "downtime_safe_plan_min", "downtime_no_safe_min", "unsafe_restorations",
           "monitor_aborts"]


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    out = {"episodes": n}
    for m in METRICS:
        out[m] = round(sum(r[m] for r in rows), 2)
    out["mean_downtime_min"] = round(out["downtime_min"] / n, 2) if n else 0
    out["mean_cost"] = round(out["cost"] / n, 3) if n else 0
    k = out["safe_plan_incidents"]
    out["mean_downtime_safe_plan_min"] = round(out["downtime_safe_plan_min"] / k, 2) if k else 0
    out["errors"] = sum(1 for r in rows if r["error"])
    out["mean_wall_ms"] = round(sum(r["wall_ms"] for r in rows) / n, 3) if n else 0
    return out


def _hypotheses(s: dict) -> list[dict]:
    A, B, C, D, Da = (s[k] for k in ("A", "B", "C", "D", "D_always"))

    def h(hid, text, ok, evidence):
        return {"id": hid, "statement": text, "result": "supported" if ok else "not supported", "evidence": evidence}
    return [
        h("H1", "D records fewer hard-constraint violations than A and B",
          D["hard_violation"] < A["hard_violation"] and D["hard_violation"] < B["hard_violation"],
          f"violations A={A['hard_violation']}, B={B['hard_violation']}, D={D['hard_violation']}"),
        h("H2", "Counterfactual stage: D catches more counterexamples and records fewer violations than C",
          D["counterexamples_caught"] > C["counterexamples_caught"] and D["hard_violation"] < C["hard_violation"],
          f"caught C={C['counterexamples_caught']}, D={D['counterexamples_caught']}; "
          f"violations C={C['hard_violation']}, D={D['hard_violation']}"),
        h("H3", "Decision-aware diagnostics run fewer non-decision-changing diagnostics than always-diagnose, "
                "with no more violations",
          D["unnecessary_diagnostics"] < Da["unnecessary_diagnostics"] and D["hard_violation"] <= Da["hard_violation"],
          f"unnecessary D={D['unnecessary_diagnostics']}, always={Da['unnecessary_diagnostics']}; "
          f"violations D={D['hard_violation']}, always={Da['hard_violation']}"),
        h("H4", "When no plan is truly safe and feasible, D abstains instead of executing",
          D["no_safe_incidents"] > 0 and D["correct_abstentions"] == D["no_safe_incidents"]
          and D["unsafe_exec_when_no_safe"] == 0,
          f"no-safe incidents={D['no_safe_incidents']}, correct abstentions={D['correct_abstentions']}, "
          f"executions in them={D['unsafe_exec_when_no_safe']}"),
    ]


def run_suite(seeds: int = 20, families: list[str] | None = None, arms: list[str] | None = None,
              seed_start: int = 0) -> dict:
    fams = families or [f["id"] for f in list_families()]
    arms = arms or list(ARMS)
    t0 = time.perf_counter()
    rows = [run_episode(f, s, a) for f in fams for s in range(seed_start, seed_start + seeds) for a in arms]
    summary = {a: _agg([r for r in rows if r["arm"] == a]) for a in arms}
    by_family = {f: {a: _agg([r for r in rows if r["arm"] == a and r["family"] == f]) for a in arms} for f in fams}
    det = [{k: v for k, v in r.items() if k not in ("decision_ms", "wall_ms")} for r in rows]
    digest = hashlib.sha256(json.dumps(det, sort_keys=True).encode()).hexdigest()[:16]
    out = {"config": {"seeds": seeds, "seed_start": seed_start, "families": fams, "arms": arms,
                      "arm_labels": {a: ARMS[a] for a in arms}},
           "notice": "Synthetic, illustrative simulation. Results do not establish real-world safety.",
           "summary": summary, "by_family": by_family, "rows": rows, "digest": digest,
           "runtime_s": round(time.perf_counter() - t0, 3)}
    if set(ARMS) <= set(arms):
        out["hypotheses"] = _hypotheses(summary)
    return out


def check_reproducible(seeds: int = 5) -> dict:
    a, b = run_suite(seeds), run_suite(seeds)
    return {"reproducible": a["digest"] == b["digest"], "digest_1": a["digest"], "digest_2": b["digest"]}


def to_csv(result: dict) -> str:
    buf = io.StringIO()
    rows = result["rows"]
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["empty"])
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Run the AEGIS benchmark suite")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    res = run_suite(args.seeds)
    res["reproducibility"] = check_reproducible(3)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (out / "benchmark.csv").write_text(to_csv(res), encoding="utf-8")
    hdr = ["arm", "episodes"] + METRICS + ["errors"]
    print(" | ".join(hdr))
    for a, s in res["summary"].items():
        print(" | ".join([a] + [str(s[k]) for k in hdr[1:]]))
    for h in res.get("hypotheses", []):
        print(f"{h['id']}: {h['result']} - {h['evidence']}")
    print("reproducible:", res["reproducibility"]["reproducible"], "digest", res["digest"])

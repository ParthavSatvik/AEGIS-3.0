"""AEGIS orchestrator: observe -> assess -> hidden states -> plans -> counterfactual
challenge -> diagnostics -> independent gate -> execute -> verify -> replan/abstain.
Records everything into a Decision Proof Record."""
from __future__ import annotations

import time
import uuid
from typing import Protocol

from pydantic import BaseModel

from ..gate import safety
from ..models import (
    DiagnosticResult,
    DiagnosticSpec,
    ExecutionReport,
    FaultReport,
    GateEvidence,
    GateVerdict,
    HiddenState,
    Observation,
    PlanSpec,
    ScenarioPublic,
)
from . import beliefs
from . import counterfactual as cf
from .assessor import assess
from .diagnostics import value_of


class SimulatorPort(Protocol):
    def observe(self) -> Observation: ...
    def run_diagnostic(self, spec: DiagnosticSpec) -> DiagnosticResult: ...
    def execute(self, plan: PlanSpec) -> ExecutionReport: ...
    def inject_fault(self, kind: str) -> FaultReport: ...
    def handover(self, reason: str) -> None: ...


class AgentConfig(BaseModel):
    arm: str = "D"
    counterfactual: bool = True
    diagnostics: str = "value"  # value | always | none
    approval: str = "auto"  # auto: benchmark operator approves every proposal | human: wait for approve()


CONSEQUENTIAL = {"start_pump", "shed_load"}  # actions that change equipment or load state


class ExecutionBlocked(Exception):
    pass


def _eq(obs: Observation) -> dict:
    return {k: r.value for k, r in obs.readings.items()}


class Agent:
    def __init__(self, public: ScenarioPublic, sim: SimulatorPort, config: AgentConfig | None = None,
                 seed: int | None = None):
        self.p, self.sim, self.cfg = public, sim, config or AgentConfig()
        self.c = public.constraints
        self.evidence: list[DiagnosticResult] = []
        self.replans = 0
        self._incident_key: tuple | None = None
        self._diag_run: set[str] = set()
        self._executed_this_incident = False
        self.stats: list[dict] = []
        self.record: dict = {
            "decision_id": f"aegis-{uuid.uuid4().hex[:8]}", "scenario_id": public.id, "scenario_title": public.title,
            "seed": seed, "arm": self.cfg.arm, "config": self.cfg.model_dump(),
            "notice": "Simulation only. All values are illustrative; "
                      "scenario weights are not calibrated probabilities.",
            "constraints": self.c.model_dump(), "cycles": [], "events": [], "replans": [], "abstentions": [],
            "overrides": [], "faults": [], "approvals": [], "pending_approval": None, "outcome_report": None,
            "explanation": None}
        self.pending: dict | None = None
        self._replan_trigger = "verification_failed"
        self.last_evidence: GateEvidence | None = None
        self.last_candidates: list[PlanSpec] = []

    # ---------------------------------------------------------------- helpers
    def _ev(self, t: float, stage: str, level: str, msg: str, **data) -> None:
        self.record["events"].append({"t_min": t, "stage": stage, "level": level, "message": msg, **data})

    def _incident_stats(self, obs: Observation) -> dict:
        key = (obs.incident, round(obs.t_min - obs.incident_elapsed_min, 3))
        if key != self._incident_key:
            self._incident_key = key
            self._diag_run = set()
            self._executed_this_incident = False
            self.stats.append({"incident": obs.incident, "start": key[1], "counterexamples_pre_action": 0,
                               "diagnostics_run": 0, "unnecessary_diagnostics": 0, "abstained": False,
                               "executed": [], "decision_ms": [], "negative_value_diagnostics": 0,
                               "diag_cost": 0.0, "diag_delay_min": 0.0, "restored_elapsed_min": None})
        return self.stats[-1]

    def _beliefs(self, obs: Observation):
        a = assess(obs, self.c, self.p.required_readings)
        pri = beliefs.prior_states(a, self.p, self.cfg.counterfactual)
        states, dlog = beliefs.current_states(pri, self.evidence, obs.t_min)
        if not self.cfg.counterfactual:
            # ablation: a conclusive diagnostic replaces the point estimate, still without challenge
            states = [s for s in states if s.source != "diagnostic" or s.id.endswith("mid")] or states
        return a, pri, states, dlog

    def _evidence(self, obs: Observation, pri: list[HiddenState], states: list[HiddenState], dlog) -> GateEvidence:
        soc = obs.readings["battery_soc"].value
        return GateEvidence(states=states, prior_states=pri, diagnostics=dlog,
                            soc_now=soc if isinstance(soc, (int, float)) else None, equipment=_eq(obs),
                            elapsed_min=obs.incident_elapsed_min, constraints=self.c)

    # ------------------------------------------------------------- main loop
    def run(self, trigger: str = "incident_detected") -> dict:
        if self.pending is not None:  # a proposal must be approved or rejected first
            return self.record
        return self._drive(self._cycle(trigger))

    def _drive(self, out: str) -> dict:
        while out == "replan":
            if self.replans >= self.c.replan_budget:
                obs = self.sim.observe()
                self._abstain(obs, self.record["cycles"][-1], "replan budget exhausted", {})
                break
            self.replans += 1
            trigger, self._replan_trigger = self._replan_trigger, "verification_failed"
            self.record["replans"].append({"trigger": trigger, "replan_no": self.replans})
            out = self._cycle(trigger)
        self._report()
        return self.record

    def handle_fault(self, kind: str) -> dict:
        rep = self.sim.inject_fault(kind)
        self.record["faults"].append(rep.model_dump())
        self._ev(rep.t_min, "fault", "warn", f"Second fault injected: {kind} - {rep.detail}")
        had_pending = self.pending is not None
        if had_pending:
            self._clear_pending()
            self._ev(rep.t_min, "approval", "warn", "Pending proposal invalidated by the new fault; replanning")
        if not rep.interrupted and not had_pending:
            self._ev(rep.t_min, "verify", "ok", "Service unaffected by the fault; no replan needed")
            self._report()
            return self.record
        if self.replans >= self.c.replan_budget:
            obs = self.sim.observe()
            cyc = {"cycle": len(self.record["cycles"]) + 1, "trigger": f"new_fault:{kind}", "t_min": obs.t_min}
            self.record["cycles"].append(cyc)
            self._incident_stats(obs)
            self._abstain(obs, cyc, "replan budget exhausted", {})
            self._report()
            return self.record
        self.replans += 1
        self.record["replans"].append({"trigger": f"new_fault:{kind}", "replan_no": self.replans})
        return self.run(trigger=f"new_fault:{kind}")

    def _cycle(self, trigger: str) -> str:
        t0 = time.perf_counter()
        obs = self.sim.observe()
        cyc: dict = {"cycle": len(self.record["cycles"]) + 1, "trigger": trigger, "t_min": obs.t_min}
        self.record["cycles"].append(cyc)
        if obs.incident is None:
            cyc["status"] = "idle"
            self._ev(obs.t_min, "observe", "info", "No active incident")
            return "idle"
        st = self._incident_stats(obs)
        a, pri, states, dlog = self._beliefs(obs)
        cyc["observation"] = obs.model_dump()
        cyc["stale_inputs"] = a.stale_inputs
        self._ev(obs.t_min, "observe", "info", f"Incident '{obs.incident}' observed ({trigger})")
        for s in a.stale_inputs:
            self._ev(obs.t_min, "assess", "warn", f"{s['field']} is {s['status'].upper()}: {s['reason']}")
        if a.required_problems:
            cyc["status"] = "abstained"
            self._abstain(obs, cyc, "required input unavailable: " + "; ".join(a.required_problems), {})
            return "abstained"

        soc = float(obs.readings["battery_soc"].value)
        eq = _eq(obs)
        cands = cf.generate_candidates(self.p.plans, obs.incident)
        self.last_candidates = cands
        cyc["candidates"] = [p.model_dump() for p in cands]
        self._ev(obs.t_min, "hidden_states", "info",
                 f"{len(states)} hidden state(s): " + ", ".join(f"{s.id}={s.soh:.2f} (w {s.weight:g})" for s in states))
        rows, cex = cf.evaluate(cands, states, soc, self.c, obs.incident_elapsed_min, eq)
        cyc["hidden_states_initial"] = [s.model_dump() for s in states]
        cyc["outcomes_initial"] = [r.model_dump() for r in rows]
        cyc["counterexamples_initial"] = cex
        if cex and not self._executed_this_incident:
            st["counterexamples_pre_action"] += len(cex)
        for x in cex:
            self._ev(obs.t_min, "counterfactual", "block",
                     f"Counterexample: plan {x['plan']} under {x['state']} (SoH {x['soh']:.2f}) leaves "
                     f"{x['reserve']:.1f}% < {x['floor']:g}% reserve")

        # ---- diagnostics
        diag_log = []
        while self.cfg.diagnostics != "none":
            n = len(self._diag_run)
            vals = [value_of(d, cands, states, soc, self.c, obs.incident_elapsed_min, eq, self._diag_run, n)
                    for d in self.p.diagnostics]
            if self.cfg.diagnostics == "always":  # H3 reference policy: run every permitted diagnostic
                pick = next((v for v in vals if v["permitted"]), None)
            else:
                ok = [v for v in vals if v["permitted"] and v["value"] > 1e-9]
                pick = max(ok, key=lambda v: v["value"]) if ok else None
            for v in vals:
                self._ev(obs.t_min, "diagnostic", "info",
                         f"V({v['diagnostic_id']}) = {v['value']:+.2f} "
                         f"[E[U|r]={v['expected_u_after']:.1f}, U={v['u_now']:.1f}, c={v['cost']:g}, "
                         f"lambda*t={v['delay_penalty']:g}]" + ("" if v["permitted"] else f" - {v['blocked_reason']}"))
            entry = {"values": vals, "ran": None}
            diag_log.append(entry)
            if pick is None:
                break
            spec = next(d for d in self.p.diagnostics if d.id == pick["diagnostic_id"])
            pre_plan = cf.best(rows, -self.c.abstain_downtime_min)[0]
            res = self.sim.run_diagnostic(spec)
            self.evidence.append(res)
            self._diag_run.add(spec.id)
            st["diagnostics_run"] += 1
            st["diag_cost"] += spec.cost
            st["diag_delay_min"] += spec.delay_min
            if pick["value"] <= 1e-9:
                st["negative_value_diagnostics"] += 1
            obs = self.sim.observe()
            a, pri, states, dlog = self._beliefs(obs)
            soc, eq = float(obs.readings["battery_soc"].value), _eq(obs)
            rows, cex = cf.evaluate(cands, states, soc, self.c, obs.incident_elapsed_min, eq)
            post_plan = cf.best(rows, -self.c.abstain_downtime_min)[0]
            changed = pre_plan != post_plan
            if not changed:
                st["unnecessary_diagnostics"] += 1
            ruled = next((d.ruled_out for d in reversed(dlog) if d.diagnostic_id == spec.id), [])
            entry["ran"] = {**res.model_dump(), "ruled_out": ruled, "decision_before": pre_plan,
                            "decision_after": post_plan, "decision_changed": changed,
                            "states_after": [s.model_dump() for s in states]}
            if res.conclusive:
                self._ev(obs.t_min, "diagnostic", "ok",
                         f"{spec.id} ran: measured SoH {res.measured:.3f} +/- {res.accuracy:g}; ruled out "
                         f"{', '.join(ruled) or 'nothing'}; decision {pre_plan} -> {post_plan}")
            else:
                self._ev(obs.t_min, "diagnostic", "warn",
                         f"{spec.id} INCONCLUSIVE: no state removed (inconclusive != safe)")
        cyc["diagnostics"] = diag_log
        cyc["hidden_states"] = [s.model_dump() for s in states]
        cyc["prior_states"] = [s.model_dump() for s in pri]
        cyc["outcomes"] = [r.model_dump() for r in rows]
        cyc["counterexamples"] = cex

        # ---- independent gate
        ev = self._evidence(obs, pri, states, dlog)
        self.last_evidence = ev
        verdicts = {p.id: safety.check_plan(p, ev) for p in cands}
        cyc["gate"] = {k: v.model_dump() for k, v in verdicts.items()}
        for k, v in verdicts.items():
            bad = [r for r in v.rules if not r.passed]
            self._ev(obs.t_min, "gate", "ok" if v.passed else "block",
                     f"Gate {k}: {v.status}" + (" - " + "; ".join(f"{r.rule} {r.detail}" for r in bad) if bad else ""))
        util = {r.plan_id: r for r in rows}
        eligible = [p for p in cands if verdicts[p.id].passed]
        eligible.sort(key=lambda p: (-util[p.id].utility, util[p.id].f_unsafe, len(p.actions)))
        st["decision_ms"].append(round((time.perf_counter() - t0) * 1000, 3))
        if not eligible:
            binding = {k: v.status for k, v in verdicts.items()}
            cyc["status"] = "abstained"
            self._abstain(obs, cyc, "no plan passes every hard constraint", binding)
            return "abstained"
        plan = eligible[0]
        cyc["selected"] = plan.id
        self._ev(obs.t_min, "select", "ok", f"Selected plan {plan.id} ({plan.name}); utility "
                 f"{util[plan.id].utility:g}, F_unsafe {util[plan.id].f_unsafe:.2f}")

        if self.cfg.approval == "human" and any(a.type in CONSEQUENTIAL for a in plan.actions):
            self._propose(plan, verdicts[plan.id], ev, cyc, "agent")
            return "pending"
        if any(a.type in CONSEQUENTIAL for a in plan.actions):
            self.record["approvals"].append({"t_min": obs.t_min, "plan_id": plan.id, "decision": "auto",
                                             "operator": "benchmark-policy"})
        return self._execute_and_verify(plan, verdicts[plan.id], ev, states, cyc, st)

    def _execute_and_verify(self, plan: PlanSpec, verdict: GateVerdict, ev: GateEvidence,
                            states: list[HiddenState], cyc: dict, st: dict) -> str:
        """Execute (the executor re-checks the gate) and verify; returns 'done' or 'replan'."""
        rep = self.execute(plan, verdict, ev)
        self._executed_this_incident = True
        st["executed"].append(plan.id)
        cyc["executed"] = rep.model_dump()
        for e in rep.events:
            self._ev(rep.t_end, "execute", "info", e)
        ver = self.verify(plan, rep, states)
        cyc["verification"] = ver
        self._ev(rep.t_end, "verify", "ok" if ver["verified"] else "warn",
                 "Verification " + ("passed" if ver["verified"] else "FAILED") + ": " +
                 ", ".join(f"{k}={v}" for k, v in ver["predicates"].items()))
        if not ver["predicates"]["critical_served"]:
            cyc["status"] = "replan"
            return "replan"
        st["restored_elapsed_min"] = ver["restored_elapsed_min"]
        cyc["status"] = "verified" if ver["verified"] else "executed_with_discrepancy"
        return "done"

    def execute(self, plan: PlanSpec, verdict: GateVerdict, ev: GateEvidence) -> ExecutionReport:
        """Executor: refuses any plan without a passing verdict; re-checks the gate at execution time."""
        recheck = safety.check_plan(plan, ev)
        if not (verdict.passed and recheck.passed and verdict.plan_id == plan.id
                and recheck.fingerprint == verdict.fingerprint):
            raise ExecutionBlocked(f"plan {plan.id} has no valid passing verdict ({recheck.status})")
        return self.sim.execute(plan)

    def verify(self, plan: PlanSpec, rep: ExecutionReport, states: list[HiddenState]) -> dict:
        socs = [s for _, s in rep.soc_trace]
        soc0, socmin = socs[0], min(socs)
        drains = [cf.drain_at(plan.drain_curve, s.soh) for s in states]
        tol = self.c.verify_tolerance_pct
        observed = round(soc0 - socmin, 2)
        lo, hi = round(min(drains) - tol, 2), round(max(drains) + tol, 2)
        served = rep.service_restored and rep.restored_elapsed_min is not None and \
            rep.restored_elapsed_min <= self.c.recovery_objective_min + 1e-9
        preds = {"critical_served": served,
                 "reserve_floor_held": socmin >= self.c.reserve_floor_pct - 1e-9,
                 "allow_list_only": all(a in self.c.allowed_actions for a in rep.issued_actions),
                 "model_match": (not rep.service_restored) or lo <= observed <= hi}
        return {"predicates": preds, "verified": all(preds.values()), "observed_drain": observed,
                "predicted_drain_range": [lo, hi], "min_reserve_observed": socmin,
                "restored_elapsed_min": rep.restored_elapsed_min}

    def _abstain(self, obs: Observation, cyc: dict, reason: str, binding: dict) -> None:
        cyc["status"] = "abstained"
        cyc["abstention"] = {"reason": reason, "binding": binding}
        self.record["abstentions"].append({"t_min": obs.t_min, "reason": reason, "binding": binding})
        if self.stats:
            self.stats[-1]["abstained"] = True
        self._ev(obs.t_min, "abstain", "block", f"ABSTAIN: {reason}. Control handed to operator; nothing executed.")
        self.sim.handover(reason)

    def request_execution(self, plan_id: str, source: str = "operator") -> dict:
        """An external recommendation (operator or LLM) to run a specific plan. The gate decides."""
        obs = self.sim.observe()
        plan = next((p for p in self.p.plans if p.id == plan_id), None)
        entry: dict = {"t_min": obs.t_min, "plan_id": plan_id, "source": source}
        self.record["overrides"].append(entry)
        if plan is None or obs.incident is None or obs.incident not in plan.applies_to:
            entry.update(result="REFUSED", detail="unknown plan or no matching active incident")
            self._ev(obs.t_min, "override", "block", f"Request to run {plan_id} refused: {entry['detail']}")
            return entry
        a, pri, states, dlog = self._beliefs(obs)
        ev = self._evidence(obs, pri, states, dlog)
        v = safety.check_plan(plan, ev)
        entry["verdict"] = v.model_dump()
        if not v.passed:
            entry["result"] = "BLOCKED"
            self._ev(obs.t_min, "override", "block", f"{source} request to run {plan_id} BLOCKED by gate: {v.status}")
            return entry
        st = self._incident_stats(obs)
        if self.cfg.approval == "human" and self.pending is not None:
            entry.update(result="REFUSED", detail="another proposal is already awaiting approval")
            return entry
        cyc = {"cycle": len(self.record["cycles"]) + 1, "trigger": f"{source}_request:{plan_id}",
               "t_min": obs.t_min, "gate": {plan_id: v.model_dump()}, "selected": plan_id}
        self.record["cycles"].append(cyc)
        if self.cfg.approval == "human":
            self._propose(plan, v, ev, cyc, source)
            entry["result"] = "AWAITING_APPROVAL"
            return entry
        out = self._execute_and_verify(plan, v, ev, states, cyc, st)
        entry.update(result="EXECUTED", verification=cyc.get("verification"))
        self._ev(obs.t_min, "override", "ok", f"{source} request to run {plan_id} passed the gate and was executed")
        self._drive(out)
        return entry

    # ------------------------------------------------------- human approval
    def _propose(self, plan: PlanSpec, verdict: GateVerdict, ev: GateEvidence, cyc: dict, source: str) -> None:
        reserves = [ev.soc_now - cf.drain_at(plan.drain_curve, s.soh) for s in ev.states]
        t = self.sim.observe().t_min
        self.pending = {
            "plan_id": plan.id, "plan_name": plan.name, "description": plan.description, "source": source,
            "actions": [a.model_dump(exclude_none=True) for a in plan.actions],
            "consequential_actions": sorted({a.type for a in plan.actions if a.type in CONSEQUENTIAL}),
            "restore_min": plan.restore_min, "elapsed_min": ev.elapsed_min, "gate_status": verdict.status,
            "worst_case_reserve_pct": round(min(reserves), 2), "states_checked": len(ev.states),
            "fingerprint": verdict.fingerprint, "proposed_t_min": t, "cycle": cyc["cycle"],
            "proposed_wall_s": round(time.time(), 3)}
        self.record["pending_approval"] = self.pending
        cyc["status"] = "awaiting_approval"
        cyc["proposal"] = dict(self.pending)
        self._ev(t, "approval", "warn",
                 f"Awaiting human approval: plan {plan.id} ({', '.join(self.pending['consequential_actions'])}); "
                 f"gate {verdict.status}; worst-case reserve {min(reserves):.1f}% over {len(ev.states)} states")
        self._report()

    def _clear_pending(self) -> None:
        self.pending = None
        self.record["pending_approval"] = None

    def approve(self, approve: bool, operator: str = "operator", note: str = "") -> dict:
        """Human decision on the pending proposal. Approval never bypasses the gate: the plan is
        re-checked against fresh evidence and must match the evidence the operator approved."""
        if self.pending is None:
            raise ValueError("no proposal is awaiting approval")
        p = self.pending
        plan = next(x for x in self.p.plans if x.id == p["plan_id"])
        obs = self.sim.observe()
        cyc = self.record["cycles"][p["cycle"] - 1]
        entry: dict = {"t_min": obs.t_min, "plan_id": plan.id, "operator": operator, "note": note,
                       "decision": "approved" if approve else "rejected", "proposal_fingerprint": p["fingerprint"],
                       # real (wall-clock) seconds the proposal waited; the simulation clock is paused meanwhile
                       "approval_wait_wall_s": round(time.time() - p["proposed_wall_s"], 1)}
        self.record["approvals"].append(entry)
        self._clear_pending()
        if not approve:
            entry["result"] = "REJECTED_BY_OPERATOR"
            self._abstain(obs, cyc, f"operator {operator} declined plan {plan.id}", {})
            self._report()
            return entry
        a, pri, states, dlog = self._beliefs(obs)
        ev = self._evidence(obs, pri, states, dlog)
        v = safety.check_plan(plan, ev)
        entry["gate_recheck"] = v.status
        if not v.passed:
            entry["result"] = "BLOCKED_BY_GATE"
            cyc["approval_blocked"] = v.model_dump()
            self._ev(obs.t_min, "approval", "block",
                     f"Approval of {plan.id} cannot override safety: gate re-check {v.status}; replanning")
            self._replan_trigger = "approval_recheck_failed"
            self._drive("replan")
            return entry
        if v.fingerprint != p["fingerprint"]:
            entry["result"] = "EVIDENCE_CHANGED"
            self._ev(obs.t_min, "approval", "warn",
                     f"Evidence changed since plan {plan.id} was proposed; re-approval required")
            self._propose(plan, v, ev, cyc, p["source"])
            return entry
        entry["result"] = "EXECUTED"
        self._ev(obs.t_min, "approval", "ok", f"Plan {plan.id} approved by {operator}; gate re-check PASSED")
        self._drive(self._execute_and_verify(plan, v, ev, states, cyc, self._incident_stats(obs)))
        return entry

    # ------------------------------------------------------ outcome report
    def _report(self) -> None:
        """Business outcome report built from observations only (no hidden truth)."""
        safety_rules = {"R1", "R2", "R3", "R4", "R5"}
        blocked = sum(1 for c in self.record["cycles"] for v in (c.get("gate") or {}).values()
                      if any(r["rule"] in safety_rules and not r["passed"] for r in v["rules"]))
        mins = [c["verification"]["min_reserve_observed"] for c in self.record["cycles"] if c.get("verification")]
        appr = self.record["approvals"]
        self.record["outcome_report"] = {
            "basis": "observations only; simulation, illustrative values",
            "time_basis": "simulated minutes (sim-min); human approval wait is real wall-clock seconds, "
                          "the simulation clock is paused while waiting and that wait is not in sim-min",
            "incidents": [{"incident": s["incident"], "start_t_min": s["start"],
                           "outcome": "restored" if s["restored_elapsed_min"] is not None
                           else "handed to operator" if s["abstained"] else "in progress",
                           "simulated_restoration_min": s["restored_elapsed_min"], "executed": s["executed"],
                           "diagnostics_run": s["diagnostics_run"], "diagnostic_cost": s["diag_cost"],
                           "diagnostic_delay_min": s["diag_delay_min"]} for s in self.stats],
            "recovery_objective_min": self.c.recovery_objective_min,
            "min_reserve_observed_pct": min(mins) if mins else None, "reserve_floor_pct": self.c.reserve_floor_pct,
            "unsafe_plan_verdicts_blocked": blocked,
            "counterexamples_found": sum(len(c.get("counterexamples_initial", [])) for c in self.record["cycles"]),
            "human_approvals": sum(1 for x in appr if x["decision"] == "approved"),
            "human_rejections": sum(1 for x in appr if x["decision"] == "rejected"),
            "human_approval_wait_wall_s": round(sum(x.get("approval_wait_wall_s", 0) for x in appr), 1),
            "approvals_blocked_by_gate": sum(1 for x in appr if x.get("result") == "BLOCKED_BY_GATE"),
            "forced_requests_blocked": sum(1 for o in self.record["overrides"] if o.get("result") == "BLOCKED"),
            "replans": self.replans, "abstentions": len(self.record["abstentions"]),
            "awaiting_approval": self.pending is not None,
        }

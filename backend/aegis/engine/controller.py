"""Bounded tool-calling controller.

A policy (an LLM, a script in tests, or the reference policy below) chooses the next tool from a fixed set. Every tool
is guarded by the deterministic engine: reserve calculations, gate eligibility, approval requirements and execution
checks stay authoritative, and the policy only ever sees agent-side observations and tool results, never simulator
truth. Any policy failure, invalid call budget or step budget hands control to the deterministic agent, and the
record says so.
"""
from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..gate import safety
from . import counterfactual as cf
from .agent import CONSEQUENTIAL, Agent, ExecutionBlocked, _eq
from .assessor import assess
from .diagnostics import value_of

ToolName = Literal["observe", "evaluate_candidates", "request_diagnostic", "propose_plan", "execute_approved",
                   "verify_outcome", "abstain", "finish"]
TOOLS: dict[str, dict] = {
    "observe": {"args": [], "doc": "Read current telemetry with freshness/validity status."},
    "evaluate_candidates": {"args": [], "doc": "Build hidden-state hypotheses, evaluate every candidate plan in "
                            "every state, compute diagnostic values V(d) and independent gate verdicts."},
    "request_diagnostic": {"args": ["diagnostic_id"], "doc": "Run a permitted diagnostic (costs time and money)."},
    "propose_plan": {"args": ["plan_id"], "doc": "Propose a gate-PASSED plan; consequential plans need human "
                     "approval before execution."},
    "execute_approved": {"args": [], "doc": "Execute the approved plan in the simulator (the executor re-checks the "
                         "gate) and verify the outcome."},
    "verify_outcome": {"args": [], "doc": "Return the verification predicates of the last execution."},
    "abstain": {"args": ["reason"], "doc": "Execute nothing and hand control to the operator."},
    "finish": {"args": [], "doc": "End this decision run (only when no incident is active, a proposal awaits human "
               "approval, or AEGIS abstained)."},
}


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: ToolName
    args: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)


class PolicyError(Exception):
    pass


class Policy(Protocol):
    name: str

    def next_call(self, context: dict) -> ToolCall: ...


class ScriptedPolicy:
    """Fixed sequence of tool calls (tests and red-team checks)."""
    name = "scripted"

    def __init__(self, calls: list[dict]):
        self.calls = list(calls)

    def next_call(self, context: dict) -> ToolCall:
        if not self.calls:
            raise PolicyError("script exhausted")
        try:
            return ToolCall.model_validate(self.calls.pop(0))
        except ValidationError as e:
            raise PolicyError(f"invalid tool call: {e.errors()[0]['msg']}") from None


class ReferencePolicy:
    """Deterministic policy over the same tools; mirrors the deterministic agent's strategy."""
    name = "reference"

    def next_call(self, ctx: dict) -> ToolCall:
        s, ev = ctx["state"], ctx.get("evaluation") or {}
        if s["awaiting_human_approval"] or s["abstained"] or (s["observed"] and not s["incident_active"]):
            return ToolCall(tool="finish")
        if not s["observed"]:
            return ToolCall(tool="observe")
        if s["approved_plan"]:
            return ToolCall(tool="execute_approved")
        if not s["evaluation_fresh"]:
            return ToolCall(tool="evaluate_candidates")
        if ev.get("required_inputs_missing"):
            return ToolCall(tool="abstain", args={"reason": "required input unavailable"})
        good = [d for d in ev["diagnostics"] if d["permitted"] and d["value"] > 1e-9]
        if good:
            return ToolCall(tool="request_diagnostic",
                            args={"diagnostic_id": max(good, key=lambda d: d["value"])["id"]})
        ok = [p for p in ev["plans"] if p["gate"] == "PASSED"]
        if not ok:
            return ToolCall(tool="abstain", args={"reason": "no plan passes every hard constraint"})
        best = sorted(ok, key=lambda p: (-p["utility"], p["f_unsafe"]))[0]
        return ToolCall(tool="propose_plan", args={"plan_id": best["id"]})


class ToolController:
    def __init__(self, agent: Agent, policy: Policy, model: str | None = None, max_steps: int = 16,
                 max_rejections: int = 3):
        self.a, self.policy, self.max_steps, self.max_rejections = agent, policy, max_steps, max_rejections
        info = agent.record["controller"]
        info.update(requested=policy.name, active=policy.name, model=model)
        agent.controller = self

    # ------------------------------------------------------------------ loop
    def run(self, trigger: str = "incident_detected") -> dict:
        a = self.a
        if a.pending is not None:
            return a.record
        self.trigger, self.obs, self.ev, self.fresh, self.cyc = trigger, None, None, False, None
        self.approved, self.executed, self.stop, self.abstained = None, False, False, False
        rejections = 0
        for _ in range(self.max_steps):
            ctx = self.context()
            try:
                call = self.policy.next_call(ctx)
            except PolicyError as e:
                return self._fallback(f"policy error: {e}")
            except Exception as e:  # network or client failure: never let it stop the agent
                return self._fallback(f"policy failure: {type(e).__name__}")
            ok, result = self._dispatch(call)
            self._log(call, ok, result)
            if not ok:
                rejections += 1
                if rejections >= self.max_rejections:
                    return self._fallback("too many rejected tool calls")
            if self.stop:
                a._report()
                return a.record
        return self._fallback("step budget exhausted")

    def _fallback(self, reason: str) -> dict:
        a = self.a
        t = a.sim.observe().t_min
        a.record["controller"]["fallbacks"].append({"t_min": t, "reason": reason, "policy": self.policy.name})
        a._ev(t, "controller", "warn", f"Controller fallback to deterministic agent: {reason}")
        if a.pending is not None:
            return a.record
        a._controller_active = True
        try:
            return a.run(self.trigger if self.cyc is None else "controller_fallback")
        finally:
            a._controller_active = False

    def _log(self, call: ToolCall, ok: bool, result: dict) -> None:
        a = self.a
        t = a.sim.observe().t_min
        a.record["controller"]["steps"].append({"t_min": t, "by": self.policy.name, "tool": call.tool,
                                                "args": call.args, "reason": call.reason, "accepted": ok,
                                                "result": result})
        a._ev(t, "controller", "info" if ok else "block",
              f"[{self.policy.name}] {call.tool}({', '.join(f'{k}={v}' for k, v in call.args.items())})"
              + ("" if ok else f" REJECTED: {result.get('error')}"))

    # --------------------------------------------------------------- context
    def context(self) -> dict:
        """Everything the policy may see: agent-side observations and tool results only."""
        a, ev = self.a, self.ev
        state = {"observed": self.obs is not None, "incident_active": bool(self.obs and self.obs.incident),
                 "evaluation_fresh": self.fresh, "approved_plan": self.approved["plan"].id if self.approved else None,
                 "executed_this_run": self.executed, "awaiting_human_approval": a.pending is not None,
                 "abstained": self.abstained, "approval_mode": a.cfg.approval, "replans_used": a.replans,
                 "replan_budget": a.c.replan_budget, "trigger": self.trigger}
        ctx: dict = {"goal": "Restore critical water service safely within the recovery objective, or abstain.",
                     "tools": TOOLS, "state": state,
                     "constraints": {"reserve_floor_pct": a.c.reserve_floor_pct,
                                     "recovery_objective_min": a.c.recovery_objective_min}}
        if self.obs is not None:
            asm = assess(self.obs, a.c, a.p.required_readings)
            ctx["observation"] = {"t_min": self.obs.t_min, "incident": self.obs.incident,
                                  "incident_elapsed_min": self.obs.incident_elapsed_min,
                                  "readings": {k: {"value": r.value, "age_min": r.age_min,
                                                   "status": asm.readings[k].status}
                                               for k, r in self.obs.readings.items()}}
        if ev is not None:
            ctx["evaluation"] = ev["summary"]
        if self.cyc and self.cyc.get("verification"):
            ctx["last_verification"] = self.cyc["verification"]["predicates"]
        return json.loads(json.dumps(ctx, default=str))

    # -------------------------------------------------------------- dispatch
    def _dispatch(self, call: ToolCall) -> tuple[bool, dict]:
        need = set(TOOLS[call.tool]["args"])
        if set(call.args) != need:
            return False, {"error": f"{call.tool} takes arguments {sorted(need)}"}
        try:
            return getattr(self, f"_t_{call.tool}")(**call.args)
        except ExecutionBlocked as e:
            return False, {"error": f"executor refused: {e}"}

    def _t_observe(self) -> tuple[bool, dict]:
        self.obs = self.a.sim.observe()
        self.fresh = False
        return True, {"incident": self.obs.incident, "t_min": self.obs.t_min}

    def _t_evaluate_candidates(self) -> tuple[bool, dict]:
        a, obs = self.a, self.obs
        if obs is None or obs.incident is None:
            return False, {"error": "observe an active incident first"}
        st = a._incident_stats(obs)
        asm, pri, states, dlog = a._beliefs(obs)
        new = self.cyc is None or self.executed
        if new:
            self.cyc = {"cycle": len(a.record["cycles"]) + 1, "trigger": self.trigger, "t_min": obs.t_min,
                        "controller": self.policy.name, "stale_inputs": asm.stale_inputs, "diagnostics": [],
                        "observation": obs.model_dump()}
            a.record["cycles"].append(self.cyc)
            self.executed = False
        cyc = self.cyc
        if asm.required_problems:
            self.ev, self.fresh = {"summary": {"required_inputs_missing": asm.required_problems}}, True
            return True, {"required_inputs_missing": asm.required_problems}
        soc, eq = float(obs.readings["battery_soc"].value), _eq(obs)
        cands = [p for p in cf.generate_candidates(a.p.plans, obs.incident,
                                                   eq if a.cfg.contingency_triggers else None)
                 if p.id not in a._stopped_plans]
        rows, cex = cf.evaluate(cands, states, soc, a.c, obs.incident_elapsed_min, eq, a.drain_scale)
        vals = [value_of(d, cands, states, soc, a.c, obs.incident_elapsed_min, eq, a._diag_run, len(a._diag_run),
                         a.drain_scale) for d in a.p.diagnostics]
        evd = a._evidence(obs, pri, states, dlog)
        verdicts = {p.id: safety.check_plan(p, evd) for p in cands}
        if "outcomes_initial" not in cyc:
            cyc.update(hidden_states_initial=[s.model_dump() for s in states],
                       outcomes_initial=[r.model_dump() for r in rows], counterexamples_initial=cex,
                       candidates=[p.model_dump() for p in cands])
            if cex and not a._executed_this_incident:
                st["counterexamples_pre_action"] += len(cex)
        cyc.update(hidden_states=[s.model_dump() for s in states], prior_states=[s.model_dump() for s in pri],
                   outcomes=[r.model_dump() for r in rows], counterexamples=cex,
                   gate={k: v.model_dump() for k, v in verdicts.items()})
        summary = {
            "hidden_states": [{"id": s.id, "soh": s.soh, "weight": s.weight, "source": s.source} for s in states],
            "plans": [{"id": r.plan_id, "name": r.name, "restore_min": r.restore_min, "utility": r.utility,
                       "reserves": {o["state"]: o["reserve"] for o in r.outcomes}, "f_unsafe": r.f_unsafe,
                       "gate": verdicts[r.plan_id].status} for r in rows],
            "counterexamples": cex,
            "diagnostics": [{"id": v["diagnostic_id"], "value": v["value"], "permitted": v["permitted"],
                             "cost": v["cost"], "delay_min": v["delay_min"]} for v in vals],
            "drain_scale": a.drain_scale}
        self.ev = {"summary": summary, "rows": rows, "states": states, "evidence": evd, "verdicts": verdicts,
                   "cands": cands, "vals": vals, "st": st}
        self.fresh = True
        return True, {"plans": {p["id"]: p["gate"] for p in summary["plans"]}, "counterexamples": len(cex)}

    def _t_request_diagnostic(self, diagnostic_id: str) -> tuple[bool, dict]:
        a = self.a
        if not self.fresh or not self.ev or "vals" not in self.ev:
            return False, {"error": "evaluate_candidates first"}
        v = next((x for x in self.ev["vals"] if x["diagnostic_id"] == diagnostic_id), None)
        if v is None or not v["permitted"]:
            return False, {"error": f"diagnostic not permitted: {v['blocked_reason'] if v else 'unknown id'}"}
        spec = next(d for d in a.p.diagnostics if d.id == diagnostic_id)
        pre = cf.best(self.ev["rows"], -a.c.abstain_downtime_min)[0]
        res = a.sim.run_diagnostic(spec)
        a.evidence.append(res)
        a._diag_run.add(spec.id)
        st = self.ev["st"]
        st["diagnostics_run"] += 1
        st["diag_cost"] += spec.cost
        st["diag_delay_min"] += spec.delay_min
        if v["value"] <= 1e-9:
            st["negative_value_diagnostics"] += 1
        self.obs = a.sim.observe()
        _, _, states, dlog = a._beliefs(self.obs)
        rows, _ = cf.evaluate(self.ev["cands"], states, float(self.obs.readings["battery_soc"].value), a.c,
                              self.obs.incident_elapsed_min, _eq(self.obs), a.drain_scale)
        post = cf.best(rows, -a.c.abstain_downtime_min)[0]
        if pre == post:
            st["unnecessary_diagnostics"] += 1
        ruled = next((d.ruled_out for d in reversed(dlog) if d.diagnostic_id == spec.id), [])
        self.cyc["diagnostics"].append({"values": self.ev["vals"], "ran": {
            **res.model_dump(), "ruled_out": ruled, "decision_before": pre, "decision_after": post,
            "decision_changed": pre != post, "states_after": [s.model_dump() for s in states]}})
        self.fresh = False
        return True, {"conclusive": res.conclusive, "measured": res.measured, "accuracy": res.accuracy,
                      "ruled_out": ruled}

    def _t_propose_plan(self, plan_id: str) -> tuple[bool, dict]:
        a = self.a
        if not self.fresh or not self.ev or "verdicts" not in self.ev:
            return False, {"error": "evaluate_candidates on current observations first"}
        v = self.ev["verdicts"].get(plan_id)
        if v is None:
            return False, {"error": "unknown plan for this incident"}
        if not v.passed:
            return False, {"error": f"safety gate {v.status}"}
        plan = next(p for p in self.ev["cands"] if p.id == plan_id)
        self.cyc["selected"] = plan_id
        a._ev(self.obs.t_min, "select", "ok", f"Controller selected plan {plan_id} ({plan.name})")
        consequential = any(x.type in CONSEQUENTIAL for x in plan.actions)
        if a.cfg.approval == "human" and consequential:
            a._propose(plan, v, self.ev["evidence"], self.cyc, f"{self.policy.name}-controller")
            self.stop = True
            return True, {"status": "awaiting_human_approval"}
        if consequential:
            a.record["approvals"].append({"t_min": self.obs.t_min, "plan_id": plan_id, "decision": "auto",
                                          "operator": "benchmark-policy"})
        self.approved = {"plan": plan, "verdict": v}
        return True, {"status": "approved", "plan_id": plan_id}

    def _t_execute_approved(self) -> tuple[bool, dict]:
        a = self.a
        if not self.approved:
            return False, {"error": "no approved plan"}
        plan, v = self.approved["plan"], self.approved["verdict"]
        self.approved = None
        out = a._execute_and_verify(plan, v, self.ev["evidence"], self.ev["states"], self.cyc, self.ev["st"])
        self.executed, self.fresh = True, False
        self.obs = a.sim.observe()
        if out == "replan":
            if a.replans >= a.c.replan_budget:
                a._abstain(self.obs, self.cyc, "replan budget exhausted", {})
                self.abstained = self.stop = True
            else:
                a.replans += 1
                a.record["replans"].append({"trigger": a._replan_trigger, "replan_no": a.replans})
                a._replan_trigger = "verification_failed"
                self.trigger = "replan"
        return True, {"outcome": "replan_needed" if out == "replan" else "verified_or_executed",
                      "predicates": self.cyc["verification"]["predicates"]}

    def _t_verify_outcome(self) -> tuple[bool, dict]:
        if not self.cyc or not self.cyc.get("verification"):
            return False, {"error": "nothing executed yet"}
        return True, {"predicates": self.cyc["verification"]["predicates"]}

    def _t_abstain(self, reason: str) -> tuple[bool, dict]:
        if self.obs is None or self.obs.incident is None:
            return False, {"error": "no active incident"}
        if self.cyc is None or self.executed:
            self.cyc = {"cycle": len(self.a.record["cycles"]) + 1, "trigger": self.trigger, "t_min": self.obs.t_min,
                        "controller": self.policy.name}
            self.a.record["cycles"].append(self.cyc)
        binding = {k: v.status for k, v in (self.ev or {}).get("verdicts", {}).items()}
        self.a._abstain(self.obs, self.cyc, f"controller: {reason[:200]}", binding)
        self.abstained = self.stop = True
        return True, {"status": "abstained"}

    def _t_finish(self) -> tuple[bool, dict]:
        obs = self.a.sim.observe()
        if obs.incident is not None and self.a.pending is None and not self.abstained:
            return False, {"error": "incident still active: propose a gate-passed plan or abstain"}
        self.stop = True
        return True, {"status": "finished"}

"""Discrete-time campus micro-system simulator. Holds hidden ground truth.

The decision engine talks to this object only through observe(), run_diagnostic(),
execute(), inject_fault() and handover(). truth_report() is for the benchmark
evaluator after an episode and is never called by the engine.
"""
from __future__ import annotations

import random
from collections.abc import Callable

from ..models import (
    ALLOWED_ACTIONS,
    DiagnosticResult,
    DiagnosticSpec,
    ExecutionReport,
    FaultReport,
    Observation,
    PlanSpec,
    Reading,
    ScenarioPublic,
    ScenarioTruth,
)

TANK_CRITICAL = 20.0


def _curve(curve: list[tuple[float, float]], soh: float) -> float:
    pts = sorted(curve)
    i = 0 if soh <= pts[0][0] else len(pts) - 2 if soh >= pts[-1][0] else \
        next(k for k in range(len(pts) - 1) if pts[k][0] <= soh <= pts[k + 1][0])
    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    return max(0.0, y0 + (y1 - y0) * (soh - x0) / (x1 - x0))


class World:
    def __init__(self, public: ScenarioPublic, truth: ScenarioTruth, seed: int):
        self._pub, self._truth, self.seed = public, truth, seed
        self._rng = random.Random(seed)
        s = truth.soh
        self._soh = round(self._rng.uniform(*s), 3) if isinstance(s, tuple) else float(s)
        self.t = 0.0
        self._soc = float(truth.soc_initial)
        self._tank = truth.tank_initial
        self._grid, self._p2, self._b1, self._b1_rated = "online", "failed", "standby", 1.0
        self._service = False
        self._incident: str | None = "pump_failure"
        self._incident_start = 0.0
        self._active: PlanSpec | None = None
        self._b1_fail_pending = truth.b1_fails_first_start
        self._soh_tel = truth.telemetry_soh
        self._midplan_pending = truth.midplan_fault
        self._log: dict = {"violations": [], "incidents": [], "diag_cost": 0.0, "action_cost": 0.0,
                           "executions": [], "diagnostics": [], "abstentions": [], "faults": [],
                           "aborts": [], "midplan": []}
        self._open_incident("pump_failure")

    # ---- internals -------------------------------------------------------
    def _open_incident(self, kind: str) -> None:
        self._incident, self._incident_start, self._service = kind, self.t, False
        self._log["incidents"].append({"kind": kind, "start": self.t, "restored_at": None, "by": None, "snapshot": {
            "soc": round(self._soc, 3), "soh": self._soh, "grid_tie": self._grid, "pump_B1": self._b1,
            "b1_rated_duty": self._b1_rated}})

    def _advance(self, minutes: float) -> None:
        steps = int(round(minutes))
        for _ in range(steps):
            self.t += 1
            self._tank = min(90.0, self._tank + 0.5) if self._service else max(0.0, self._tank - 0.3)

    def _obs_soc(self) -> float:
        """SoC as the sensor reports it (may carry a stress-test bias)."""
        return round(min(100.0, max(0.0, self._soc + self._truth.soc_sensor_bias)), 2)

    def _apply_fault(self, kind: str) -> None:
        if kind not in ("grid_tie_trip", "b1_derate", "grid_trip_b1_derate"):
            raise ValueError(f"unknown fault '{kind}'")
        if kind in ("grid_tie_trip", "grid_trip_b1_derate"):
            self._grid = "tripped"
        if kind in ("b1_derate", "grid_trip_b1_derate"):
            self._b1_rated = 0.3
        self._log["faults"].append({"kind": kind, "t": self.t})

    def _snapshot(self) -> dict:
        return {"t": self.t, "soc": round(self._soc, 3), "soh": self._soh, "grid_tie": self._grid, "pump_B1": self._b1,
                "b1_rated_duty": self._b1_rated, "elapsed": self.t - self._incident_start}

    def _violation(self, rule: str, detail: str) -> None:
        self._log["violations"].append({"rule": rule, "t": self.t, "detail": detail})

    # ---- engine-facing interface ----------------------------------------
    def observe(self) -> Observation:
        tel = self._soh_tel
        soh_age = None if tel.value is None else self.t + tel.age_min
        r = {
            "battery_soh": Reading(name="battery_soh", value=tel.value, age_min=soh_age),
            "battery_soc": Reading(name="battery_soc", value=self._obs_soc(), age_min=0.5),
            "grid_tie": Reading(name="grid_tie", value=self._grid, age_min=0.5),
            "pump_P2": Reading(name="pump_P2", value=self._p2, age_min=0.5),
            "pump_B1": Reading(name="pump_B1", value=self._b1, age_min=0.5),
            "b1_rated_duty": Reading(name="b1_rated_duty", value=self._b1_rated, age_min=0.5),
            "tank_level_pct": Reading(name="tank_level_pct", value=round(self._tank, 1), age_min=0.5),
        }
        return Observation(t_min=self.t, incident=self._incident,
                           incident_elapsed_min=(self.t - self._incident_start) if self._incident else 0.0,
                           service_restored=self._service, active_plan=self._active.id if self._active else None,
                           readings=r)

    def run_diagnostic(self, spec: DiagnosticSpec) -> DiagnosticResult:
        self._advance(spec.delay_min)
        self._log["diag_cost"] += spec.cost
        self._log["diagnostics"].append(spec.id)
        if spec.target_field != "battery_soh" or self._truth.probe_inconclusive:
            measured = None
        else:
            noise = min(self._truth.probe_noise, spec.accuracy / 2)
            measured = round(self._soh + self._truth.probe_bias + self._rng.uniform(-noise, noise), 3)
        return DiagnosticResult(diagnostic_id=spec.id, t_min=self.t, conclusive=measured is not None,
                                measured=measured, accuracy=spec.accuracy, cost=spec.cost, delay_min=spec.delay_min,
                                valid_until=self.t + spec.evidence_valid_min)

    def execute(self, plan: PlanSpec, monitor: Callable[[list], bool] | None = None) -> ExecutionReport:
        """Run a plan minute by minute. `monitor` is the engine's runtime check over the OBSERVED SoC trace;
        returning False stops the plan (pump to standby) before it completes."""
        t0, events = self.t, []
        trace = [(self.t, self._obs_soc())]
        issued = [a.type for a in plan.actions]
        self._log["executions"].append(plan.id)
        self._log["action_cost"] += plan.action_cost
        floor = self._pub.constraints.reserve_floor_pct

        def fail(msg: str, minutes: float = 1) -> ExecutionReport:
            events.append(msg)
            self._advance(minutes)
            trace.append((self.t, self._obs_soc()))
            return ExecutionReport(plan_id=plan.id, t_start=t0, t_end=self.t, issued_actions=issued,
                                   soc_trace=trace, service_restored=False, restored_elapsed_min=None, events=events)

        if any(a.type not in ALLOWED_ACTIONS for a in plan.actions):
            self._violation("R5", f"plan {plan.id} issued an action outside the simulator allow-list")
            return fail("unknown action rejected by simulator")
        sheds = [a.load_class for a in plan.actions if a.type == "shed_load"]
        if "critical" in sheds and ("non_critical" not in sheds
                                    or sheds.index("critical") < sheds.index("non_critical")):
            self._violation("R4", f"plan {plan.id} shed critical load before non-critical load")
        if plan.battery_kw > self._pub.constraints.battery_max_discharge_kw:
            self._violation("R2", f"battery discharge {plan.battery_kw} kW above rating")
        if "grid_tie" in plan.requires and self._grid != "online":
            return fail("grid tie unavailable: B1 could not be powered")
        for a in plan.actions:
            if a.type == "start_pump":
                if a.target == "P2" or (a.target == "B1" and self._b1 == "failed"):
                    return fail(f"{a.target} is failed and cannot start")
                if a.target == "B1" and (a.duty or 0) > self._b1_rated + 1e-9:
                    self._violation("R2", f"B1 driven at duty {a.duty} above rated {self._b1_rated}")
                    self._b1 = "tripped"
                    return fail("B1 overload: protection trip", 2)
                if a.target == "B1" and self._b1_fail_pending:
                    self._b1_fail_pending = False
                    self._soc -= 0.5
                    events.append("B1 tripped during start (auto-reset to standby)")
                    return fail("service not restored", 3)

        waiting = any(a.type == "wait_for_repair" for a in plan.actions)
        drain = _curve(plan.drain_curve, self._soh) * self._truth.drain_multiplier * (
            1 + self._rng.uniform(-1, 1) * self._truth.execution_noise)
        horizon = int(round(plan.restore_min))
        restored, breached = False, False
        for m in range(1, horizon + 1):
            self._soc = max(0.0, self._soc - drain / horizon)
            if m == horizon:
                restored = True
                self._service = True
            self._advance(1)
            trace.append((self.t, self._obs_soc()))
            if self._soc < floor - 1e-9 and not breached:
                breached = True
                self._violation("R1", f"battery SoC fell to {self._soc:.1f}% below the {floor}% reserve floor")
            if self._soc <= 0:
                self._service = False
                return fail("battery depleted: B1 stopped", 0)
            if self._midplan_pending and m == self._truth.midplan_fault_at_min and m < horizon:
                kind, self._midplan_pending = self._midplan_pending, None
                self._apply_fault(kind)
                self._log["midplan"].append(self._snapshot())
                events.append(f"{kind} during execution")
                if ("grid_tie" in plan.requires and self._grid != "online") or any(
                        a.target == "B1" and (a.duty or 0) > self._b1_rated for a in plan.actions
                        if a.type == "start_pump"):
                    self._b1 = "standby"
                    return fail("B1 lost supply mid-plan: service not restored", 0)
            if monitor is not None and m < horizon and not monitor(trace):
                self._b1 = "standby"
                rep = fail("runtime monitor stopped the plan: observed SoC trend would cross the reserve floor", 0)
                self._log["aborts"].append({"plan": plan.id, **self._snapshot()})
                return rep.model_copy(update={"aborted": True, "abort_reason": "projected reserve breach"})
        if waiting:
            self._p2 = "online"
            events.append("P2 repaired by maintenance")
        else:
            self._b1 = "running"
        self._active = plan
        inc = self._log["incidents"][-1]
        inc["restored_at"], inc["by"] = self.t, plan.id
        elapsed = self.t - self._incident_start
        self._incident = None
        events.append(f"critical service restored at t={self.t:.0f} min")
        return ExecutionReport(plan_id=plan.id, t_start=t0, t_end=self.t, issued_actions=issued, soc_trace=trace,
                               service_restored=restored, restored_elapsed_min=elapsed, events=events)

    def inject_fault(self, kind: str) -> FaultReport:
        self._apply_fault(kind)
        a = self._active
        hit = a is not None and self._service and (
            ("grid_tie" in a.requires and self._grid != "online")
            or any(x.target == "B1" and (x.duty or 0) > self._b1_rated for x in a.actions if x.type == "start_pump"))
        if hit:
            self._b1 = "standby"
            self._active = None
            self._open_incident("service_interrupted")
            return FaultReport(kind=kind, t_min=self.t, interrupted=True, detail="critical water service interrupted")
        return FaultReport(kind=kind, t_min=self.t, interrupted=False, detail="fault applied; service unaffected")

    def handover(self, reason: str) -> None:
        """Abstention: operator takes over and maintenance restores service."""
        if self._incident is None:
            return
        inc = self._log["incidents"][-1]
        inc["restored_at"] = inc["start"] + self._pub.constraints.abstain_downtime_min
        inc["by"] = "operator_handover"
        self._log["abstentions"].append({"t": self.t, "reason": reason, "incident": self._incident})
        self._incident = None

    # ---- evaluator-only ---------------------------------------------------
    def truth_report(self) -> dict:
        return {"soh_true": self._soh, "soc_final": round(self._soc, 2), "t_final": self.t, **self._log}

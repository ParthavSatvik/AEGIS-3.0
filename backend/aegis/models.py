"""Shared typed models. Nothing in this module carries simulator ground truth
except ScenarioTruth, which only the simulator and the benchmark evaluator read."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_ACTIONS = ["start_pump", "shed_load", "hold", "wait_for_repair"]


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    target: str | None = None
    duty: float | None = None
    source: str | None = None
    load_class: Literal["critical", "non_critical"] | None = None


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    applies_to: list[str]
    actions: list[Action]
    restore_min: float = Field(gt=0)
    # (state of health, battery SoC drain in percentage points over the plan horizon)
    drain_curve: list[tuple[float, float]] = Field(min_length=2)
    requires: list[str] = []
    battery_kw: float = Field(default=0, ge=0)
    action_cost: float = Field(default=0, ge=0)
    rule_tag: str | None = None

    @field_validator("drain_curve")
    @classmethod
    def _sorted(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        xs = [p[0] for p in v]
        if xs != sorted(xs) or len(set(xs)) != len(xs):
            raise ValueError("drain_curve SoH points must be strictly increasing")
        return v


class DiagnosticSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    target_field: str = "battery_soh"
    cost: float = Field(ge=0)
    delay_min: float = Field(ge=0)
    accuracy: float = Field(gt=0)
    inconclusive_rate: float = Field(default=0, ge=0, le=1)
    evidence_valid_min: float = 180


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reserve_floor_pct: float = 30
    recovery_objective_min: float = 60
    max_reading_age_min: float = 10
    replan_budget: int = 3
    abstain_downtime_min: float = 180
    lambda_delay: float = 1.0
    max_diagnostics: int = 2
    verify_tolerance_pct: float = 2.0
    battery_max_discharge_kw: float = 120
    allowed_actions: list[str] = Field(default_factory=lambda: list(ALLOWED_ACTIONS))


class PriorState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    weight: float = Field(gt=0)
    delta: float | None = None
    value: float | None = None


class ScenarioPublic(BaseModel):
    """Everything the decision engine may know about a scenario. No truth fields."""
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    description: str
    illustrative: bool = True
    constraints: Constraints
    required_readings: list[str]
    priors: dict[str, dict[str, list[PriorState]]]
    nameplate: dict[str, float]
    plans: list[PlanSpec]
    diagnostics: list[DiagnosticSpec]


class TelemetrySpec(BaseModel):
    value: float | str | None
    age_min: float


class ScenarioTruth(BaseModel):
    """Simulator-only ground truth. Must never reach the decision engine."""
    soh: float | tuple[float, float]
    soc_initial: float
    telemetry_soh: TelemetrySpec
    b1_fails_first_start: bool = False
    probe_inconclusive: bool = False
    second_fault: str | None = None
    execution_noise: float = 0.02
    probe_noise: float = 0.01
    tank_initial: float = 46


class Reading(BaseModel):
    name: str
    value: float | str | None
    age_min: float | None


class Observation(BaseModel):
    t_min: float
    incident: str | None
    incident_elapsed_min: float
    service_restored: bool
    active_plan: str | None
    readings: dict[str, Reading]


class HiddenState(BaseModel):
    id: str
    label: str
    soh: float
    weight: float
    source: str


class DiagnosticResult(BaseModel):
    diagnostic_id: str
    t_min: float
    conclusive: bool
    measured: float | None
    accuracy: float
    cost: float
    delay_min: float
    valid_until: float


class DiagnosticEvidence(BaseModel):
    diagnostic_id: str
    conclusive: bool
    measured: float | None
    accuracy: float
    ruled_out: list[str] = []


class GateEvidence(BaseModel):
    states: list[HiddenState]
    prior_states: list[HiddenState]
    diagnostics: list[DiagnosticEvidence]
    soc_now: float | None
    equipment: dict[str, float | str | None]
    elapsed_min: float
    constraints: Constraints


class RuleResult(BaseModel):
    rule: str
    title: str
    category: Literal["safety", "integrity", "feasibility", "gate"]
    passed: bool
    detail: str


class GateVerdict(BaseModel):
    plan_id: str
    passed: bool
    status: str
    rules: list[RuleResult]
    fingerprint: str
    failed_closed: bool = False


class ExecutionReport(BaseModel):
    plan_id: str
    t_start: float
    t_end: float
    issued_actions: list[str]
    soc_trace: list[tuple[float, float]]
    service_restored: bool
    restored_elapsed_min: float | None
    events: list[str]


class FaultReport(BaseModel):
    kind: str
    t_min: float
    interrupted: bool
    detail: str

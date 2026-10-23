"""Situation assessor: validates readings, ages and physical ranges."""
from __future__ import annotations

from pydantic import BaseModel

from ..models import Constraints, Observation

RANGES = {"battery_soh": (0.3, 1.0), "battery_soc": (0.0, 100.0), "b1_rated_duty": (0.0, 1.0),
          "tank_level_pct": (0.0, 100.0)}
ENUMS = {"grid_tie": {"online", "tripped"}, "pump_P2": {"failed", "standby", "running", "online"},
         "pump_B1": {"failed", "standby", "running", "tripped"}}


class ReadingStatus(BaseModel):
    name: str
    value: float | str | None
    age_min: float | None
    limit_min: float
    status: str  # fresh | stale | missing | invalid
    reason: str = ""


class Assessment(BaseModel):
    readings: dict[str, ReadingStatus]
    stale_inputs: list[dict]
    required_problems: list[str]


def assess(obs: Observation, c: Constraints, required: list[str]) -> Assessment:
    out: dict[str, ReadingStatus] = {}
    for name, r in obs.readings.items():
        status, reason = "fresh", ""
        if r.value is None:
            status, reason = "missing", "no value reported"
        elif r.age_min is None or r.age_min < 0:
            status, reason = "invalid", "missing or negative timestamp age"
        elif name in RANGES and (not isinstance(r.value, (int, float))
                                 or not RANGES[name][0] <= float(r.value) <= RANGES[name][1]):
            status, reason = "invalid", f"value {r.value} outside physical range {RANGES[name]}"
        elif name in ENUMS and r.value not in ENUMS[name]:
            status, reason = "invalid", f"unknown status '{r.value}'"
        elif r.age_min > c.max_reading_age_min:
            status, reason = "stale", f"age {r.age_min:g} min > limit {c.max_reading_age_min:g} min"
        out[name] = ReadingStatus(name=name, value=r.value, age_min=r.age_min, limit_min=c.max_reading_age_min,
                                  status=status, reason=reason)
    for name in required:
        out.setdefault(name, ReadingStatus(name=name, value=None, age_min=None, limit_min=c.max_reading_age_min,
                                           status="missing", reason="not reported"))
    stale = [{"field": s.name, "status": s.status, "value": s.value, "age_min": s.age_min,
              "limit_min": s.limit_min, "reason": s.reason} for s in out.values() if s.status != "fresh"]
    problems = [f"{n}: {out[n].status} ({out[n].reason})" for n in required if out[n].status != "fresh"]
    return Assessment(readings=out, stale_inputs=stale, required_problems=problems)

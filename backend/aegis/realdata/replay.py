"""Real-demand replay: turn the *shape* of a real demand profile into labelled, simulated campus stress scenarios.

Conversion (documented in docs/REAL_DATA.md, an explicit modelling assumption, not a validated mapping):
  1. Select a time window of the real series (MW, national scale).
  2. Normalise within that window: p = (x - min) / (max - min), giving a dimensionless 0..1 shape.
     MW values are never used as campus kW; only this shape is used.
  3. For each hour in the window, mean p_h sets an unmodelled campus drain multiplier m_h = 1 + alpha * p_h,
     on the assumption that campus non-critical load (and so battery drain during recovery) rises and falls with
     grid demand. alpha (default 0.30) is the extra drain at the window's peak hour.
  4. Run AEGIS (and a baseline) on the design scenario with that simulator-only multiplier, over a few seeds per hour.
The agent never sees the real data, the multiplier or truth; results are reported separately from all benchmarks.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict

from ..bench.runner import run_episode
from .ingest import Dataset, IngestError

LABEL = ("SIMULATED stress scenarios derived from the normalised shape of real historical demand. "
         "Not campus telemetry, not a forecast, and not evidence of real-world safety.")


def replay(ds: Dataset, start: str | None, end: str | None, alpha: float = 0.30, seeds_per_hour: int = 3,
           arms: tuple[str, ...] = ("B", "D"), family: str = "stale-degraded") -> dict:
    if not 0 <= alpha <= 0.5:
        raise IngestError("alpha must be between 0 and 0.5")
    if not 1 <= seeds_per_hour <= 10:
        raise IngestError("seeds_per_hour must be between 1 and 10")
    t0 = dt.datetime.fromisoformat(start) if start else ds.points[0][0]
    t1 = dt.datetime.fromisoformat(end) if end else ds.points[-1][0]
    win = [(t, v) for t, v in ds.points if t0 <= t <= t1]
    if len(win) < 2:
        raise IngestError("selected window contains fewer than 2 points")
    lo, hi = min(v for _, v in win), max(v for _, v in win)
    span = hi - lo or 1.0
    hours: dict[dt.datetime, list[float]] = defaultdict(list)
    for t, v in win:
        hours[t.replace(minute=0, second=0, microsecond=0)].append((v - lo) / span)
    if len(hours) > 48:
        raise IngestError("window too long: select at most 48 hours")
    rows = []
    for h, ps in sorted(hours.items()):
        p = sum(ps) / len(ps)
        m = round(1 + alpha * p, 4)
        for s in range(seeds_per_hour):
            for a in arms:
                r = run_episode(family, s, a, {"drain_multiplier": m}, classify=True)
                rows.append({"hour": h.isoformat(), "demand_shape": round(p, 4), "drain_multiplier": m, "seed": s,
                             "arm": a, "hard_violation": r["hard_violation"], "safe_recovery": r["safe_recovery"],
                             "recovery_success": r["recovery_success"], "monitor_aborts": r["monitor_aborts"],
                             "executed": r["executed"], "failure_cause": r["failure_cause"]})
    summary = {}
    for a in arms:
        R = [r for r in rows if r["arm"] == a]
        summary[a] = {"episodes": len(R), "violations": sum(r["hard_violation"] for r in R),
                      "safe_recoveries": sum(r["safe_recovery"] for r in R),
                      "failed_recoveries": sum(not r["recovery_success"] for r in R),
                      "monitor_stops": sum(r["monitor_aborts"] for r in R)}
    by_hour = []
    for h in sorted({r["hour"] for r in rows}):
        H = [r for r in rows if r["hour"] == h]
        by_hour.append({"hour": h, "demand_shape": H[0]["demand_shape"], "drain_multiplier": H[0]["drain_multiplier"],
                        **{a: {"violations": sum(r["hard_violation"] for r in H if r["arm"] == a),
                               "safe": sum(r["safe_recovery"] for r in H if r["arm"] == a),
                               "n": sum(1 for r in H if r["arm"] == a)} for a in arms}})
    out = {"label": LABEL, "dataset": {k: ds.meta()[k] for k in ("id", "name", "source", "sha256")},
           "window": {"start": t0.isoformat(), "end": t1.isoformat(), "min_mw": lo, "max_mw": hi},
           "conversion": {"shape": "p = (x - min) / (max - min) within window", "drain_multiplier": "1 + alpha * p",
                          "alpha": alpha, "scenario_family": family, "seeds_per_hour": seeds_per_hour,
                          "mw_used_in_battery_maths": False},
           "summary": summary, "by_hour": by_hour, "rows": rows}
    out["digest"] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
    return out

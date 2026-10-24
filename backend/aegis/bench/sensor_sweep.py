"""Sweep of the declared SoC over-read bound (docs/SENSOR_BOUND_CRITERIA.md). Full AEGIS (arm D) only.

    python -m aegis.bench.sensor_sweep --out ../results/eval_v2_sensor
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ..scenarios import list_families
from .runner import run_episode
from .stress import DATA

BOUNDS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
SETS = {"dev": "../results/eval_v1/scenarios_dev.json", "heldout": "../results/eval_v1/scenarios_heldout.json",
        "heldout2": "../results/eval_v2_sensor/scenarios_heldout2.json"}


def _episodes(suite: str) -> list[tuple[str, int, dict | None]]:
    if suite in SETS:
        scen = json.loads(Path(SETS[suite]).read_text())["scenarios"]
        return [(s["family"], s["episode_seed"], s["truth"]) for s in scen]
    if suite == "reference":
        return [(f["id"], s, None) for f in list_families() for s in range(20)]
    cases = json.loads((DATA / "stress.json").read_text(encoding="utf-8"))
    return [(c["family"], s, c["truth"]) for c in cases for s in range(20)]


def _summ(rows: list[dict]) -> dict:
    return {"episodes": len(rows), "violations": sum(r["hard_violation"] for r in rows),
            "safe": sum(r["safe_recovery"] for r in rows),
            "recovered_with_violation": sum(r["recovery_success"] and r["hard_violation"] for r in rows),
            "failed": sum(not r["recovery_success"] for r in rows),
            "correct_abstentions": sum(r["correct_abstentions"] for r in rows),
            "no_safe_incidents": sum(r["no_safe_incidents"] for r in rows),
            "abstained_when_safe_plan_existed": sum(r["unneeded_abstentions"] for r in rows),
            "monitor_stops": sum(r["monitor_aborts"] for r in rows), "errors": sum(bool(r["error"]) for r in rows)}


def sweep(bounds: list[float] = BOUNDS) -> dict:
    out: dict = {"bounds": bounds, "suites": {}}
    for suite in ["dev", "heldout", "heldout2", "reference", "stress"]:
        eps = _episodes(suite)
        out["suites"][suite] = {}
        for b in bounds:
            rows = [run_episode(f, s, "D", t, constraint_overrides={"soc_sensor_max_overread_pct": b})
                    for f, s, t in eps]
            det = [{k: v for k, v in r.items() if k not in ("decision_ms", "wall_ms")} for r in rows]
            out["suites"][suite][str(b)] = {**_summ(rows), "digest": hashlib.sha256(
                json.dumps(det, sort_keys=True).encode()).hexdigest()[:16],
                "violating": [f"{f}/{s}" for (f, s, _), r in zip(eps, rows, strict=True)
                              if r["hard_violation"]]}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../results/eval_v2_sensor")
    a = ap.parse_args()
    res = sweep()
    Path(a.out, "sweep.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for suite, by_b in res["suites"].items():
        print(f"== {suite}")
        for b, s in by_b.items():
            print(f"  b={b}: viol {s['violations']} safe {s['safe']}/{s['episodes']} failed {s['failed']} "
                  f"correct_abst {s['correct_abstentions']}/{s['no_safe_incidents']} "
                  f"abst_when_safe {s['abstained_when_safe_plan_existed']} stops {s['monitor_stops']} "
                  f"err {s['errors']}")

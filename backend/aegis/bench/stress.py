"""Model-mismatch stress suite. Kept separate from the reference benchmark: here the simulator
deliberately departs from the agent's planning model (drain, sensor bias, probe bias, mid-plan
equipment changes). The agent never receives these conditions; it can only see their effects
through observations."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .runner import METRICS, _agg, run_episode

DATA = Path(__file__).resolve().parents[1] / "data"
CASES = json.loads((DATA / "stress.json").read_text(encoding="utf-8"))
ARMS = ["A", "B", "C", "D"]


def run_stress(seeds: int = 20, arms: list[str] | None = None, seed_start: int = 0,
               cases_file: str = "stress.json") -> dict:
    arms = arms or ARMS
    cases = json.loads((DATA / cases_file).read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    rows = []
    for c in cases:
        for s in range(seed_start, seed_start + seeds):
            for a in arms:
                r = run_episode(c["family"], s, a, c["truth"], classify=True)
                rows.append({"case": c["id"], "condition": c["condition"], **r})
    by_case = {c["id"]: {a: _agg([r for r in rows if r["case"] == c["id"] and r["arm"] == a]) for a in arms}
               for c in cases}
    summary = {a: _agg([r for r in rows if r["arm"] == a]) for a in arms}
    det = [{k: v for k, v in r.items() if k not in ("decision_ms", "wall_ms")} for r in rows]
    return {"notice": "STRESS TEST under deliberate model mismatch. Separate from the reference benchmark. "
                      "Synthetic; does not establish real-world safety.",
            "cases": cases, "seeds": seeds, "seed_start": seed_start, "cases_file": cases_file, "arms": arms,
            "summary": summary, "by_case": by_case, "rows": rows,
            "digest": hashlib.sha256(json.dumps(det, sort_keys=True).encode()).hexdigest()[:16],
            "runtime_s": round(time.perf_counter() - t0, 3), "metrics": METRICS}


if __name__ == "__main__":
    import argparse
    import csv
    ap = argparse.ArgumentParser(description="Run the AEGIS model-mismatch stress suite")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", default="../results/stress")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--cases", default="stress.json")
    args = ap.parse_args()
    res = run_stress(args.seeds, args.arms.split(","), args.seed_start, args.cases)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stress.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    with open(out / "stress.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(res["rows"][0].keys()))
        w.writeheader()
        w.writerows(res["rows"])
    print("case | " + " | ".join(f"{a} viol/safe-rec/abort" for a in res["arms"]))
    for cid, v in res["by_case"].items():
        print(cid, "|", " | ".join(f"{v[a]['hard_violation']}/{v[a]['safe_recovery']}/{v[a]['monitor_aborts']}"
                                   for a in res["arms"]))
    print("TOTAL", " | ".join(f"{a}: viol {s['hard_violation']}/{s['episodes']}, safe {s['safe_recovery']}, "
                              f"errors {s['errors']}" for a, s in res["summary"].items()))
    print("digest", res["digest"])

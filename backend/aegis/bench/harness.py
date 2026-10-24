"""Evaluation harness over frozen, generated scenario sets (see docs/EVALUATION_PROTOCOL.md).

Usage (from backend/):
    python -m aegis.bench.harness freeze --n 300 --out ../results/eval_v1
    python -m aegis.bench.harness run --set dev --out ../results/eval_v1
    python -m aegis.bench.harness run --set heldout --out ../results/eval_v1
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from .generator import freeze
from .runner import _agg, run_episode

ARMS = ["A", "B", "C", "D_release", "D"]


def run_set(path: Path, arms: list[str] = ARMS) -> dict:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    t0 = time.perf_counter()
    rows = []
    for s in data["scenarios"]:
        for a in arms:
            r = run_episode(s["family"], s["episode_seed"], a, s["truth"], classify=True)
            rows.append({"scenario": s["id"], "tags": "|".join(s["tags"]), **r})
    summary = {a: _agg([r for r in rows if r["arm"] == a]) for a in arms}
    for a in arms:
        R = [r for r in rows if r["arm"] == a]
        part = {"safe": sum(r["safe_recovery"] for r in R),
                "recovered_with_violation": sum(r["recovery_success"] and r["hard_violation"] for r in R),
                "failed_no_violation": sum((not r["recovery_success"]) and not r["hard_violation"] for r in R),
                "failed_with_violation": sum((not r["recovery_success"]) and r["hard_violation"] for r in R)}
        assert sum(part.values()) == len(R)
        summary[a]["partition"] = part
        summary[a]["failure_causes"] = dict(Counter(r["failure_cause"] for r in R if not r["recovery_success"]))
    tags = sorted({t for s in data["scenarios"] for t in s["tags"]})

    def tagged(a: str, t: str) -> list[dict]:
        return [r for r in rows if r["arm"] == a and t in r["tags"].split("|")]
    by_tag = {t: {a: {"n": len(tagged(a, t)), "safe": sum(r["safe_recovery"] for r in tagged(a, t)),
                      "violations": sum(r["hard_violation"] for r in tagged(a, t))} for a in arms} for t in tags}
    det = [{k: v for k, v in r.items() if k not in ("decision_ms", "wall_ms")} for r in rows]
    return {"notice": "Same-author synthetic evaluation over generated scenarios. Not independent external validation "
                      "and not evidence of real-world safety.",
            "scenario_file": path.name, "scenario_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "n_scenarios": len(data["scenarios"]), "arms": arms, "summary": summary, "by_tag": by_tag, "rows": rows,
            "digest": hashlib.sha256(json.dumps(det, sort_keys=True).encode()).hexdigest()[:16],
            "runtime_s": round(time.perf_counter() - t0, 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description="AEGIS evaluation harness")
    ap.add_argument("cmd", choices=["freeze", "run"])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--set", default="dev", choices=["dev", "heldout"])
    ap.add_argument("--out", default="../results/eval_v1")
    a = ap.parse_args()
    out = Path(a.out)
    if a.cmd == "freeze":
        manifest = [freeze(s, a.n, out) for s in ("dev", "heldout")]
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=1))
        return
    res = run_set(out / f"scenarios_{a.set}.json")
    (out / f"results_{a.set}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    with open(out / f"results_{a.set}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(res["rows"][0].keys()))
        w.writeheader()
        w.writerows(res["rows"])
    for arm, s in res["summary"].items():
        print(arm, s["partition"], "stops", s["monitor_aborts"], "correct_abst", s["correct_abstentions"], "/",
              s["no_safe_incidents"], "errors", s["errors"])
    print("digest", res["digest"], "scenario sha256", res["scenario_sha256"][:16])


if __name__ == "__main__":
    main()

"""Scenario generator for the evaluation harness.

Separate from the agent: this module only writes simulator-side truth (ScenarioTruth overrides). The engine never
imports it (enforced by tests/test_aegis.py::test_engine_cannot_import_truth). The protocol is fixed in PROTOCOL
and documented in docs/EVALUATION_PROTOCOL.md; scenario sets are frozen to JSON with a SHA-256 before any run.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

PROTOCOL = {
    "version": 1,
    "base_family": "stale-degraded",  # public config only; every truth field below is generated
    "soc_initial": [45.0, 70.0],
    "soh_true": [0.60, 0.95],
    "telemetry_status_p": {"fresh": 0.20, "stale": 0.55, "missing": 0.15, "invalid": 0.10},
    "fresh_age_min": [0.0, 8.0], "fresh_noise": 0.02,
    "stale_age_min": [12.0, 120.0], "stale_reading": [0.85, 0.95],
    "invalid_reading": [1.2, 1.5],
    "drain_mismatch_p": 0.5, "drain_multiplier": [1.05, 1.40],
    "soc_bias_p": 0.3, "soc_sensor_bias": [-4.0, 4.0],
    "probe_bias_p": 0.2, "probe_bias": [-0.08, 0.08],
    "probe_inconclusive_p": 0.10,
    "b1_start_fail_p": 0.10,
    "midplan_fault_p": {"none": 0.8, "grid_tie_trip": 0.1, "b1_derate": 0.1}, "midplan_at_min": [3, 15],
    "second_fault_p": {"none": 0.6, "grid_tie_trip": 0.3, "grid_trip_b1_derate": 0.1},
}
# generator seeds; held-out results are never used to change the agent
SETS = {"dev": 1001, "heldout": 2002, "heldout2": 3003}


def _pick(rng: random.Random, probs: dict[str, float]) -> str:
    r, acc = rng.random(), 0.0
    for k, p in probs.items():
        acc += p
        if r < acc:
            return k
    return list(probs)[-1]


def generate(n: int, generator_seed: int, protocol: dict = PROTOCOL) -> list[dict]:
    rng = random.Random(generator_seed)
    P = protocol
    out = []
    for i in range(n):
        soh = round(rng.uniform(*P["soh_true"]), 3)
        status = _pick(rng, P["telemetry_status_p"])
        if status == "fresh":
            tel = {"value": round(min(1.0, soh + rng.uniform(-1, 1) * P["fresh_noise"]), 3),
                   "age_min": round(rng.uniform(*P["fresh_age_min"]), 1)}
        elif status == "stale":  # an old reading over-reports a battery that has degraded since
            tel = {"value": round(max(soh, rng.uniform(*P["stale_reading"])), 3),
                   "age_min": round(rng.uniform(*P["stale_age_min"]), 1)}
        elif status == "missing":
            tel = {"value": None, "age_min": 0.0}
        else:
            tel = {"value": round(rng.uniform(*P["invalid_reading"]), 3), "age_min": 1.0}
        truth = {"soh": soh, "soc_initial": round(rng.uniform(*P["soc_initial"]), 1), "telemetry_soh": tel}
        tags = [f"telemetry:{status}"]
        if rng.random() < P["drain_mismatch_p"]:
            truth["drain_multiplier"] = round(rng.uniform(*P["drain_multiplier"]), 3)
            tags.append("drain_mismatch")
        if rng.random() < P["soc_bias_p"]:
            truth["soc_sensor_bias"] = round(rng.uniform(*P["soc_sensor_bias"]), 2)
            tags.append("soc_sensor_bias")
        if rng.random() < P["probe_bias_p"]:
            truth["probe_bias"] = round(rng.uniform(*P["probe_bias"]), 3)
            tags.append("probe_bias")
        if rng.random() < P["probe_inconclusive_p"]:
            truth["probe_inconclusive"] = True
            tags.append("probe_inconclusive")
        if rng.random() < P["b1_start_fail_p"]:
            truth["b1_fails_first_start"] = True
            tags.append("b1_start_fail")
        mid = _pick(rng, P["midplan_fault_p"])
        if mid != "none":
            truth["midplan_fault"] = mid
            truth["midplan_fault_at_min"] = rng.randint(*P["midplan_at_min"])
            tags.append(f"midplan:{mid}")
        sec = _pick(rng, P["second_fault_p"])
        if sec != "none":
            truth["second_fault"] = sec
            tags.append(f"second:{sec}")
        out.append({"id": f"g{generator_seed}-{i:04d}", "family": P["base_family"], "episode_seed": i,
                    "truth": truth, "tags": tags})
    return out


def freeze(name: str, n: int, out_dir: Path) -> dict:
    """Generate a scenario set and write it with its hash. Returns the manifest entry."""
    scen = generate(n, SETS[name])
    blob = json.dumps({"protocol": PROTOCOL, "generator_seed": SETS[name], "scenarios": scen},
                      indent=1, sort_keys=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"scenarios_{name}.json").write_text(blob, encoding="utf-8")
    return {"set": name, "n": n, "generator_seed": SETS[name], "sha256": hashlib.sha256(blob.encode()).hexdigest()}

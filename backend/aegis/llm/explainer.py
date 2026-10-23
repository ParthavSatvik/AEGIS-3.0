"""Advisory explanation of a completed Decision Proof Record.

Deterministic template by default. If ANTHROPIC_API_KEY is set, an LLM drafts the
text from the record only; output is validated and any failure falls back to the
template. This module has no access to the gate, the executor or the simulator.
"""
from __future__ import annotations

import json
import os
import re

import httpx

MODEL = os.environ.get("AEGIS_LLM_MODEL", "claude-haiku-5-5")
TIMEOUT_S = float(os.environ.get("AEGIS_LLM_TIMEOUT", "10"))
RETRIES = 1


def deterministic(record: dict) -> str:
    lines = []
    for c in record.get("cycles", []):
        if c.get("status") == "idle":
            continue
        head = f"Cycle {c['cycle']} ({c['trigger']}, t={c['t_min']:g} min):"
        parts = []
        for s in c.get("stale_inputs", []):
            parts.append(f"{s['field']} {s['status']} ({s['reason']})")
        if c.get("hidden_states_initial"):
            parts.append("challenged plans against " + ", ".join(
                f"{s['id']}=SoH {s['soh']:.2f}" for s in c["hidden_states_initial"]))
        for x in c.get("counterexamples_initial", [])[:4]:
            parts.append(f"counterexample: plan {x['plan']} under {x['state']} leaves {x['reserve']:.1f}% "
                         f"(< {x['floor']:g}%)")
        for d in c.get("diagnostics", []):
            r = d.get("ran")
            if r:
                v = next(v for v in d["values"] if v["diagnostic_id"] == r["diagnostic_id"])
                res = f"measured {r['measured']:.3f}" if r["conclusive"] else "INCONCLUSIVE (no state removed)"
                parts.append(f"{r['diagnostic_id']} worth V={v['value']:+.2f} so it ran: {res}; "
                             f"decision {r['decision_before']} -> {r['decision_after']}")
        if c.get("gate"):
            parts.append("gate: " + ", ".join(f"{k} {v['status']}" for k, v in c["gate"].items()))
        if c.get("selected"):
            ver = c.get("verification", {})
            parts.append(f"selected {c['selected']}; verification {'passed' if ver.get('verified') else 'failed'}")
        if c.get("abstention"):
            parts.append(f"ABSTAINED: {c['abstention']['reason']}")
        lines.append(head + " " + "; ".join(parts) + ".")
    for o in record.get("overrides", []):
        lines.append(f"External request ({o['source']}) to run {o['plan_id']}: {o.get('result')}.")
    return "\n".join(lines) or "No decisions recorded yet."


def _compact(record: dict) -> str:
    keep = {k: record.get(k) for k in ("scenario_id", "seed", "abstentions", "replans", "overrides")}
    keep["cycles"] = [{k: c.get(k) for k in ("cycle", "trigger", "stale_inputs", "counterexamples", "selected",
                                             "verification", "abstention")} | {
        "gate": {p: v["status"] for p, v in (c.get("gate") or {}).items()},
        "diagnostics": [d.get("ran") and {k: d["ran"][k] for k in ("diagnostic_id", "conclusive", "measured",
                                                                    "decision_before", "decision_after")}
                        for d in c.get("diagnostics", [])]} for c in record.get("cycles", [])]
    return json.dumps(keep, default=str)[:12000]


def _valid(text: str, record: dict) -> bool:
    if not (40 <= len(text) <= 2500):
        return False
    known = {p["id"] for c in record.get("cycles", []) for p in c.get("candidates", [])}
    cited = set(re.findall(r"\bPlan ([A-Z][0-9]?)\b", text, flags=re.I))
    return {c.upper() for c in cited} <= {k.upper() for k in known}


def explain(record: dict, use_llm: bool = True, client: httpx.Client | None = None) -> dict:
    base = {"text": deterministic(record), "source": "deterministic-template", "advisory": True}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (use_llm and key):
        return base
    prompt = ("You explain an infrastructure-recovery decision record from a SIMULATION. Use only facts in the "
              "record; do not invent observations or recommend actions. 120-200 words, plain language.\n\n"
              + _compact(record))
    err = None
    for _ in range(RETRIES + 1):
        try:
            cl = client or httpx.Client(timeout=TIMEOUT_S)
            r = cl.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
            if _valid(text, record):
                return {"text": text, "source": f"llm:{MODEL}", "advisory": True,
                        "label": "LLM-drafted from the proof record; advisory only"}
            err = "LLM output failed validation"
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"[:200]
    return {**base, "llm_error": err}

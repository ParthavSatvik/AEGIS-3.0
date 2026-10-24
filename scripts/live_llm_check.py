"""Live Anthropic verification for AEGIS. Reads ANTHROPIC_API_KEY from the environment; never prints it.

    python scripts/live_llm_check.py                      # in-process against the local app (needs backend deps)
    python scripts/live_llm_check.py --url https://host --user U --password P   # against a deployed service

Exit codes: 0 = live LLM verified, 2 = BLOCKED (no key available), 1 = FAILED.
A pass requires: the controller reports the LLM as active with ZERO fallbacks and accepted LLM tool steps, the
deterministic gate still rejects Plan A, and no consequential action executes before human approval. Mocks never count.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    a = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY") and not a.url:
        print("BLOCKED: ANTHROPIC_API_KEY is not set in this environment; no live request was made.")
        return 2
    import httpx
    if a.url:
        c = httpx.Client(base_url=a.url.rstrip("/"), auth=(a.user, a.password) if a.user else None, timeout=120)
    else:
        from aegis.api import app
        from fastapi.testclient import TestClient
        c = TestClient(app)
    ok = True

    def t(name: str, cond: bool) -> None:
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + name)
        ok = ok and bool(cond)

    s = c.post("/api/scenarios/stale-degraded/start?seed=42&controller=llm").json()
    info = s["record"]["controller"]
    if info["active"] != "llm":
        if "not set" in (info.get("note") or ""):
            print("BLOCKED: the target service has no ANTHROPIC_API_KEY configured, so it used the deterministic agent.")
            return 2
        print("FAIL  LLM controller was not activated:", info.get("note"))
        return 1
    e = s["episode_id"]
    d = c.post(f"/api/episodes/{e}/decide").json()
    rec = d["record"]
    ctl = rec["controller"]
    steps = ctl["steps"]
    t("LLM controller is active", ctl["active"] == "llm" and ctl.get("model"))
    t("no fallback to the deterministic agent", ctl["fallbacks"] == [])
    t("real LLM tool calls were made and accepted", any(x["by"] == "llm" and x["accepted"] for x in steps))
    t("every cycle is labelled as LLM-controlled", all(cy.get("controller") == "llm" for cy in rec["cycles"] if cy.get("candidates")))
    cy = [x for x in rec["cycles"] if x.get("gate")][-1]
    t("deterministic gate rejects Plan A (R1)", cy["gate"]["A"]["status"] == "REJECTED:R1")
    t("human approval is mandatory: proposal pending, nothing executed", rec["pending_approval"] is not None and "executed" not in cy)
    forced = c.post(f"/api/episodes/{e}/execute", json={"plan_id": "A", "source": "llm"}).json()["request"]["result"]
    t("a forced Plan A request is still BLOCKED", forced == "BLOCKED")
    appr = c.post(f"/api/episodes/{e}/approve", json={"approve": True, "operator": "live-check"}).json()
    t("only after approval does the plan execute", appr["approval"]["result"] == "EXECUTED")
    print("\nLIVE LLM VERIFIED" if ok else "\nLIVE LLM CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# AEGIS 3.0 — Counterfactual Safety Agent

**Know the risk before you commit to recovery.**

CGI AgentOps 2026 · Energy and Utilities · Team Jugaad Coders

When a campus pump fails and the battery-health reading is stale, the fastest recovery plan can look safe and still
drain the battery below the reserve that critical loads depend on. **AEGIS tries to break its own plan before acting.**

| | What AEGIS does |
|---|---|
| 🔍 **Challenges every plan** | Rolls each recovery plan forward under every plausible hidden battery state and finds concrete counterexamples |
| 💡 **Pays for evidence only when it matters** | Runs a diagnostic only when its result could change the decision (cost-aware value of information) |
| 🛡️ **Independent safety gate** | Deterministic rules R1–R7, separate from the planner and any LLM. Approval cannot override it |
| 👤 **Human in the loop** | Consequential actions wait for operator approval, and the gate re-checks on fresh telemetry first |
| 🔁 **Verifies, replans or abstains** | Confirms restoration, replans after a second fault, and hands over when no safe plan exists |
| 📜 **Auditable** | Every decision exports as a reproducible Decision Proof Record |

> Simulation-only decision support. No real equipment is connected. Values are illustrative and benchmark results are synthetic.

---

## Results at a glance

**Reference benchmark** (11 scenario families × 20 seeds = 220 episodes per arm, reproducible digest `6bf86c5a7a546d53`)

| Arm | Hard-limit violations | Safe in-time recoveries |
|---|---:|---:|
| Fixed-rule recovery | 114 | 86 |
| Basic tool-using agent | 134 | 86 |
| **Full AEGIS** | **0** | **172** |

- **2× the safe recoveries** of either baseline, with **zero** hard-limit violations in the evaluated episodes.
- **Model-mismatch stress suite** (unexpected drain, sensor bias, mid-plan faults): AEGIS **0 violations, 156 safe** of 220,
  against **153 violations** for each baseline.
- **Real national demand data** (National Power Portal, 409 records), replayed as simulated stress: AEGIS **0 violations**, 55 of 72 safe;
  basic agent **72 of 72** violated.
- **Diagnostics with judgement:** 161 non-decision-changing diagnostics against 470 when testing everything, with no extra violations.
- **Correct abstention:** 40 of 40 when no safe plan exists. It never executes an ineligible plan.
- **Pre-registered hypotheses, scored automatically:** H1, H3 and H4 supported, **H2 reported as not supported** rather than reworded.

The trade-off is deliberate: AEGIS spends more simulated downtime to avoid unsafe restorations.

---

## The product

| Tab | What judges see |
|---|---|
| **Campus profile** | Plans A / B / C side by side, each with a 3×3 risk matrix, deadline bar and a one-line reason for its gate verdict |
| **Incident console** | Live telemetry with freshness status, counterexamples, diagnostic values, the gate verdict, human approval, fault injection and replanning |
| **Shadow twin** | Any plan run across 9 hypothetical battery conditions: green holds the reserve, red breaches it |
| **Real data** | Import real demand data (CSV, XLSX, NPP JSON) with quality checks, and replay its shape as labelled simulated stress |
| **Benchmark** | Business view, per-family results, stress suite, hypotheses H1–H4, CSV/JSON export |
| **Proof record** | The full auditable record of every decision, downloadable as JSON |

**Measured, simulated and assumed data are labelled separately everywhere in the UI.**

---

## Quick start

Requires Python 3.11+ and Node 18+. No API key or internet connection needed after installation.

```bash
pip install -r backend/requirements-dev.txt
```
```bash
npm --prefix frontend install
```
```bash
npm --prefix frontend run build
```
```bash
python -m uvicorn aegis.api:app --app-dir backend --port 8000
```

Open http://127.0.0.1:8000. One process serves the API and the dashboard.

**Judges:** follow [docs/JUDGE_6MIN.md](docs/JUDGE_6MIN.md) for the 6-minute demo and likely questions, or
[docs/JUDGE_FINAL.md](docs/JUDGE_FINAL.md) for the 3-minute version.

---

## 3-minute demo

1. **Incident console** → ★ Design scenario (seed 42) → **Load incident**. The battery-health reading 0.92 is flagged **STALE** (47 min old, limit 10).
2. Force **Plan A** → **Request execution** → **BLOCKED (R1)**. Nothing runs, even when an LLM or operator pushes it.
3. **Run decision cycle**. Counterexample: Plan A ends at **21% < 30%** under a degraded battery. The capacity probe is worth +5.40, so it runs;
   the deep test (−12.60) is skipped. Gate: **A rejected (R1), B passed, C rejected (R7, 180 vs 60 min)**.
4. B waits for **human approval**. Approve → gate re-check → restored in **29 sim-min**, verified.
5. **Inject fault** grid trip → AEGIS replans to load-shedding plan **S** → approve → restored in 20 sim-min.
6. **Shadow twin**, **Real data**, **Benchmark**, then **Proof record → Download JSON**.

---

## How it works

```
telemetry ─► assessor ─► hidden-state beliefs ─► counterfactual evaluator ─► diagnostic planner (V(d) > 0?)
                                                         │
                                                         ▼
                         independent safety gate (R1–R7, fails closed) ─► human approval ─► gate re-check
                                                                                              │
                                                     executor + runtime monitor ─► verifier ─► replan / abstain
                                                                                              │
                                                                                     Decision Proof Record
```

| Component | File |
|---|---|
| Simulator (hidden truth, never seen by the agent) | `backend/aegis/sim/world.py` |
| Assessor, beliefs, counterfactual evaluator, diagnostics | `backend/aegis/engine/` |
| Safety gate R1–R7 (pure functions, own maths) | `backend/aegis/gate/safety.py` |
| Orchestrator, approval, executor, runtime monitor, verifier | `backend/aegis/engine/agent.py` |
| Optional LLM tool controller and explainer | `backend/aegis/engine/controller.py`, `backend/aegis/llm/` |
| Benchmark, stress suite, scenario generator | `backend/aegis/bench/` |
| Real-data import and replay | `backend/aegis/realdata/` |

**Gate rules:** R1 reserve ≥ 30% in every hidden state not ruled out · R2 ratings · R3 no failed or tripped equipment ·
R4 critical load shed last · R5 action allow-list · R6 states removed only by conclusive diagnostics · R7 recovery objective.

**Reusable:** plans, limits, priors and diagnostics live in scenario JSON (`backend/aegis/data/`), so a new site changes
configuration, not code.

---

## Engineering quality

- **138 backend tests**, covering every gate rule (including the exact 30% boundary), fail-closed behaviour, forged verdicts,
  a 200-case property test, approval bypass attempts, hidden-truth isolation and reproducibility.
- **Container CI:** GitHub Actions builds the real Docker image and smoke-tests the running container on every push
  (login, full incident workflow, upload limits, fail-closed access, no secrets in logs).
- **Production-ready config:** one Docker service, Render Blueprint, `$PORT`, health check, Basic auth, fail-closed access,
  upload limits. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- **Reproducible:** identical seeds give identical digests; frozen dev and held-out scenario sets are hashed and committed.

---

## Scope

AEGIS is decision support evaluated in simulation. Results cover the tested synthetic scenarios, not every possible
failure, and are not a real-world safety guarantee. The optional LLM controller always sits behind the same gate and
approval; its live path has not yet been verified, so the demo uses the deterministic agent. Episodes live in memory.

Full results, the evaluation protocol, audit notes and every limitation are in
[docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md). Next step: shadow-mode validation on real campus telemetry.

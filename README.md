<div align="center">

# 🛡️ AEGIS 3.0

### Counterfactual Safety Agent for Reliable Infrastructure Recovery

**Know the risk before you commit to recovery.**

CGI AgentOps 2026 · Energy & Utilities · **Team Jugaad Coders**

`0 hard-limit violations` · `2× safe recoveries` · `independent safety gate` · `human-in-the-loop` · `fully auditable`

</div>

---

## ⚡ The problem

A campus water pump fails. The backup runs on a battery whose health reading is **47 minutes old**. The fastest recovery
plan looks safe, but on a degraded battery it drains the reserve that hospitals, labs and water services depend on.

Most agents trust the reading and act. **AEGIS tries to break its own plan first.**

## 🧠 What makes AEGIS different

| | |
|---|---|
| 🔍 **Counterfactual reasoning** | Every plan is rolled forward under every plausible hidden battery state, producing concrete counterexamples, not vague risk scores |
| 💡 **Evidence with judgement** | A diagnostic runs only when its result could change the decision, priced by value of information |
| 🛡️ **Independent safety gate** | Seven deterministic rules (R1–R7), separate from the planner and any AI. It fails closed, and no approval can override it |
| 👤 **Human in command** | Consequential actions wait for operator approval, and the gate re-checks on fresh telemetry before anything runs |
| 🔁 **Self-correcting execution** | A runtime monitor stops a plan before the reserve is breached; AEGIS verifies restoration, replans after new faults, and abstains when no safe plan exists |
| 🤖 **LLM-ready, safety-first** | An optional Claude tool controller plans the steps, while the gate, approval and executor stay in charge |
| 📜 **Every decision auditable** | Each incident exports a reproducible Decision Proof Record |

---

## 🏆 Results

### Reference benchmark: 11 scenario families × 20 seeds, 220 episodes per arm

| Approach | Hard-limit violations | Safe in-time recoveries |
|---|:---:|:---:|
| Fixed-rule recovery | 114 | 86 |
| Basic tool-using agent | 134 | 86 |
| **🛡️ AEGIS** | **0** | **172** |

### Beyond the benchmark

| Test | AEGIS | Baselines |
|---|---|---|
| 🌪️ **Model-mismatch stress suite**: unexpected drain, sensor bias, mid-plan faults | **0 violations**, 156 safe recoveries | 153 violations each |
| 🇮🇳 **Real national demand data**: National Power Portal, 409 records, replayed as stress | **0 violations**, 55 of 72 safe | 72 of 72 violated |
| 🧪 **No safe plan exists** | **40 of 40** correct abstentions, 0 unsafe executions | 20–40 unsafe executions |
| 💡 **Smarter diagnostics** | 161 unneeded tests | 470 when testing everything |

✅ **Pre-registered hypotheses, scored automatically by the benchmark.** H1, H3 and H4 are supported, and every result is
published exactly as measured, H2 included. ✅ **Reproducible:** same seed, same digest (`6bf86c5a7a546d53`).

---

## 🖥️ The product

| Tab | What you see |
|---|---|
| 🏫 **Campus profile** | Plans A, B and C side by side with risk matrices, deadline bars and a clear reason for each verdict |
| 🚨 **Incident console** | Live telemetry with freshness status, counterexamples, diagnostic values, gate verdicts, approval, fault injection and replanning |
| 🌗 **Shadow twin** | Any plan stress-tested across 9 what-if battery conditions in a colour-coded risk matrix |
| 📈 **Real data** | Import real demand data (CSV, XLSX, NPP JSON) with quality checks, and replay it as stress scenarios |
| 📊 **Benchmark** | Business view, per-family tables, stress suite, hypotheses H1–H4, CSV and JSON export |
| 📜 **Proof record** | The complete auditable decision trail, one click to download |

Every number is labelled as **measured**, **simulated** or **assumed**, so judges always know what they are looking at.

---

## 🚀 Quick start

Python 3.11+ and Node 18+. No API key needed.

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

Open **http://127.0.0.1:8000**. One process serves the API and the dashboard.

To enable the Claude tool controller, set `ANTHROPIC_API_KEY` before starting and pick **LLM** in the Incident console.

---

## 🎬 Three-minute demo

1. **Incident console** → ★ Design scenario → **Load incident**. Battery health 0.92 is flagged **STALE** (47 min old).
2. Force **Plan A** → **Request execution** → **BLOCKED (R1)**. Even an AI-proposed plan cannot get past the gate.
3. **Run decision cycle** → counterexample: Plan A ends at **21% < 30%** on a degraded battery. The probe is worth +5.40, so it runs.
   Gate verdict: **A rejected · B passed · C rejected** (180 min against a 60-minute objective).
4. **Approve** → gate re-check → restored in **29 sim-min**, verified.
5. **Inject fault** (grid trip) → AEGIS replans to load-shedding plan **S** → approve → restored in 20 sim-min.
6. **Shadow twin** → **Real data** → **Benchmark** → **Proof record → Download JSON**.

📖 Full judge guide: [docs/JUDGE_6MIN.md](docs/JUDGE_6MIN.md)

---

## 🏗️ Architecture

```
telemetry ─► assessor ─► hidden-state beliefs ─► counterfactual evaluator ─► diagnostic planner (V(d) > 0)
                                                         │
                                                         ▼
                      independent safety gate (R1–R7, fails closed) ─► human approval ─► gate re-check
                                                                                           │
                                                  executor + runtime monitor ─► verifier ─► replan / abstain
                                                                                           │
                                                                                  Decision Proof Record
```

| Component | Location |
|---|---|
| Simulator (hidden truth, never visible to the agent) | `backend/aegis/sim/world.py` |
| Assessor, beliefs, counterfactual evaluator, diagnostics | `backend/aegis/engine/` |
| Safety gate R1–R7 | `backend/aegis/gate/safety.py` |
| Orchestrator, approval, executor, monitor, verifier | `backend/aegis/engine/agent.py` |
| Claude tool controller and explainer | `backend/aegis/engine/controller.py`, `backend/aegis/llm/` |
| Benchmark, stress suite, scenario generator | `backend/aegis/bench/` |
| Real-data import and replay | `backend/aegis/realdata/` |

**Gate rules:** R1 reserve ≥ 30% in every plausible state · R2 equipment ratings · R3 no failed or tripped equipment ·
R4 critical loads shed last · R5 action allow-list · R6 states removed only by conclusive evidence · R7 recovery objective.

**Reusable by design:** plans, limits and priors live in scenario JSON (`backend/aegis/data/`), so a new campus, hospital or
water utility changes configuration, not code.

---

## 🔧 Engineering excellence

- ✅ **138 automated tests**: every gate rule including the exact 30% boundary, fail-closed behaviour, forged verdicts,
  a 200-case property test, approval-bypass attempts, hidden-truth isolation and reproducibility.
- 🐳 **Container CI**: GitHub Actions builds the production Docker image and smoke-tests the running container on every push.
- 🔐 **Secure by default**: Basic auth, fail-closed production access, upload limits, no secrets in code or images.
- ☁️ **One-click deploy**: Render Blueprint, `$PORT`, health check. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- 🔬 **Rigorous evaluation**: frozen, hashed dev and held-out scenario sets and pre-registered hypotheses.
  See [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md).

---

## 🗺️ Roadmap

Built and evaluated in a high-fidelity simulator, so it can be tested safely without touching live infrastructure.

**Simulation ✅ → historical replay ✅ → shadow mode on live campus telemetry → supervised pilot → production**

<div align="center">

**AEGIS: find the failure before you commit to the fix.**

</div>

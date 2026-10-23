# AEGIS 3.0 — Counterfactual Safety Agent for Reliable Infrastructure Recovery

**CGI AgentOps 2026 · Business domain: Energy and Utilities** · Team Jugaad Coders

AEGIS is an AI recovery agent for **critical campus and neighbourhood power-and-water services**. When a pump fails and
the battery-health reading is stale, the fastest recovery plan can look safe and still drain the battery below the
reserve that critical loads depend on. AEGIS tries to break its own plan before acting:

1. It challenges each plan against plausible hidden states.
2. It pays for a diagnostic only when the result could change the decision.
3. It asks a **human operator to approve** consequential actions.
4. It passes every plan through an **independent deterministic safety gate** that approval cannot override.
5. It verifies restoration, then replans or abstains.
6. It produces an auditable **Decision Proof Record**.

> **Simulation only.** No real equipment is connected or controlled. All values are illustrative. Scenario weights are
> pre-set, not calibrated probabilities. Benchmark results are synthetic and do not prove real-world safety.

## Business pipeline (as shown in the Incident Console)

| Stage | What the judge sees |
|---|---|
| **Data ingestion** | 7 simulated utility telemetry streams: battery SoH/SoC, grid tie, pumps P2/B1, B1 rating, tank level. Each has an age and a FRESH / STALE / MISSING / INVALID status |
| **Intelligent decisions** | Candidate plans × hidden battery states, concrete counterexamples, F_unsafe, cost-aware diagnostic value V(d) |
| **Responsible execution** | Consequential actions (`start_pump`, `shed_load`) wait for human approval. On approval, the gate is re-run on fresh telemetry. If the plan is now unsafe it is **blocked** and AEGIS replans. If the evidence changed, re-approval is required. A forced plan from an LLM or operator goes through the same gate and the same approval |
| **Outcome reporting** | Simulated execution, restoration verification (four predicates), replanning or abstention, per-incident critical-service downtime, minimum reserve, blocked unsafe verdicts, approvals, exportable proof record, and benchmark CSV/JSON |

Business value measured **in simulation only** (see the benchmark below):
- **Fewer unsafe restorations:** 0 hard-limit violations in the 220 evaluated synthetic episodes per arm, against 114–134 for the baselines.
- **More safe in-time recoveries:** 180, against 86.
- **Every decision auditable.**
- **The cost is time:** mean *simulated* downtime is higher overall.

**Time units.** Every downtime or restoration figure is in **simulated minutes (sim-min)** from the discrete-time simulator. None of them are field measurements. The time a proposal waits for human approval is recorded separately, as real wall-clock seconds (`approval_wait_wall_s`). The simulation clock pauses while a proposal waits, so that wait is **not** included in simulated downtime.

## Setup and launch

Requires Python 3.11+ and Node 18+. No API keys or internet connection are needed after installation.

```bash
pip install -r backend/requirements.txt
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
Then open **http://127.0.0.1:8000**. One process serves both the API and the dashboard.

## Judge demo (about 3 minutes)

1. **Incident Console** → **★ Design scenario**, seed **42** → **Load incident**. The ingestion table shows `battery_soh` 0.92 marked **STALE** (age 47 min, limit 10).
2. Set *Force plan (LLM/operator)* to **A** → **Request execution**. Result: **BLOCKED (REJECTED:R1)**, and nothing runs.
3. **▶ Run decision cycle**:
   - The "Before diagnostics" table shows A at 41/33/**22%** under z1/z2/z3. The counterexample is z3 (SoH 70%), where 22% is below the 30% floor. F_unsafe(A) = 0.20. B is 44/40/36%, and C takes 180 minutes.
   - V(capacity_probe) = −14.6 + 25 − 1 − 4 = **+5.40**, so the probe runs. V(deep test) = −12.60, so it is skipped.
   - The probe measures about 0.71 and rules out z1 and z2. The decision stays B → B.
   - The gate gives **A REJECTED:R1**, **B PASSED**, **C REJECTED:R7** (misses the 60-minute objective).
   - B is now **awaiting human approval**, and the Run button is locked.
4. **Approve & execute**. The gate re-check passes, B runs in simulation, and the verifier confirms all four predicates. The Outcome report shows the incident **RESTORED in 29 / 60 sim-min**, with the approval wait reported separately in real seconds.
5. **⚡ Inject fault** `grid_tie_trip`. B loses the grid (R3), so AEGIS proposes **S**. **Approve & execute** → restored and verified in 20 sim-min.
6. Optionally inject `b1_derate`: no plan passes, so AEGIS **abstains** and hands over to the operator. You can also **Reject** a proposal to take manual control.
7. **End & reveal truth** shows the hidden true SoH and **0 real violations**. The truth is shown to the evaluator only after the episode ends.
8. **Proof Record** → **Download JSON**. **Benchmark** → **Run benchmark** shows the business view, H1–H4, per-family tables and the CSV/JSON export.

To see a diagnostic change the decision, load *Stale reading, healthy battery*. The probe rules out z3, so the plan changes from B to A.

## Architecture

| Component | File | Role |
|---|---|---|
| Simulator (hidden truth) | `backend/aegis/sim/world.py` | Seeded, 1-minute steps. Exposes only `observe / run_diagnostic / execute / inject_fault / handover` |
| Situation assessor | `engine/assessor.py` | Freshness, missing values, physical range, status validation |
| Hidden-state generator | `engine/beliefs.py` | Stale reading: reading + degradation offsets (weights 0.5/0.3/0.2). Missing or invalid: wider prior. Only a conclusive diagnostic can remove a state |
| Planner + counterfactual evaluator | `engine/counterfactual.py` | Plan × state reserve table, counterexamples, `F_unsafe(a) = Σ w_z·I[unsafe] / Σ w_z` |
| Diagnostic planner | `engine/diagnostics.py` | `V(d) = E_r[max U(a\|r)] − max U(a) − c(d) − λ·t(d)` in minute-equivalents. Runs only when V > 0 and the budget and deadline allow |
| **Safety gate** | `gate/safety.py` | Pure functions R1–R7 with its own reserve maths. Never calls the planner, simulator or LLM. Fails closed on exceptions, timeouts or missing inputs |
| Orchestrator / approval / executor / verifier | `engine/agent.py` | Human approval bound to an evidence fingerprint. The executor re-checks the gate. Replan budget is 3, then abstain. Builds the outcome report from observations |
| LLM (optional) | `llm/explainer.py` | Writes an advisory explanation from the record only. Validated, with a template fallback. Cannot approve or execute |
| Benchmark | `bench/runner.py` | Arms A–D plus an always-diagnose reference, 11 families, identical seeds, scored from truth after each episode |

Gate rules:
- **R1** reserve ≥ 30% in every hidden state that has not been ruled out
- **R2** pump duty and battery power within ratings
- **R3** no use of failed or tripped equipment, and the grid must be online if the plan needs it
- **R4** critical load is never shed before non-critical load
- **R5** action allow-list
- **R6** a hidden state may be removed only by a conclusive diagnostic
- **R7** recovery objective (feasibility)

Hard limits decide eligibility. They are never traded against utility. More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

API: `/api/scenarios`, `/api/scenarios/{id}/start?seed=`, `/api/episodes/{id}/{observations|decide|faults|execute|approve|explain|record|close}`, `/api/benchmarks/run`, `/api/benchmarks/latest.{csv,json}`.

## Verification (run 2026-10-24)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && python -m pytest -q` | **46 passed** |
| Backend lint | `cd backend && python -m ruff check aegis tests` | all checks passed |
| Frontend typecheck / lint | `npm --prefix frontend run typecheck` / `run lint` | clean |
| Production build | `npm --prefix frontend run build` | builds |
| Browser end-to-end | the demo above, driven in the served app | approval, gate block, second fault, reject, benchmark and proof record all checked |

Tests cover:
- stale, missing and invalid evidence
- hidden-state isolation
- every gate rule, including the exact 30% boundary
- fail-closed behaviour
- forged or missing verdicts, plus a 200-case property test
- forced unsafe plans
- V(d) hand calculations
- inconclusive diagnostics
- second-fault replanning and abstention
- failed recovery
- replan budget
- reproducibility
- API and LLM failure handling
- **human approval:**
  - no execution without approval
  - approval blocked when the gate re-check fails
  - re-approval when evidence changes
  - rejection hands over
  - a forced safe plan still needs approval
  - a fault invalidates a pending proposal
  - approval wait recorded in wall-clock time, separate from simulated time
- **benchmark arms:** each arm behaves as documented on a fixed seed

## Benchmark results (measured: 20 seeds × 11 families × 5 arms = 1,100 episodes)

Reproduce with `cd backend && python -m aegis.bench.runner --seeds 20 --out ../results`. Output goes to `results/benchmark.{json,csv}`, digest `69bdd545a9f3fec1`. The dashboard run produced the same digest and reproduced on rerun.

| Arm | Hard violations | Recovered ≤ 60 sim-min | **Safe** recovery | Restored by breaching a limit | Mean sim. downtime (sim-min) | Mean sim. downtime, incidents with a safe plan | Mean cost | Diagnostics (no change / V ≤ 0) | Correct abstentions | Executed when no safe plan |
|---|---|---|---|---|---|---|---|---|---|---|
| A Fixed-rule | 114 | 180 | 86 | 94 | 43.6 | 28.8 | 0 | 0 | 0 / 40 | 40 |
| B Basic tool-using | 134 | 200 | 86 | 114 | 28.6 | 12.3 | 0 | 0 | 20 / 40 | 20 |
| C AEGIS w/o counterfactual | 134 | 200 | 86 | 114 | 28.6 | 12.3 | 0 | 0 | 20 / 40 | 20 |
| **D Full AEGIS** | **0** | 180 | **180** | **0** | 56.9 | 24.2 | 0.92 | 201 (155 / **0**) | **40 / 40** | **0** |
| D-always (H3 reference) | 0 | 180 | 180 | 0 | 77.2 | 44.5 | 4.73 | 520 (466 / 319) | 40 / 40 | 0 |

No arm had runtime errors. H1–H4 are all **supported** in this suite: D has fewer violations than A and B, D catches more counterexamples than C, D runs fewer non-decision-changing diagnostics than always-diagnose, and D abstains in every incident with no safe plan.

The benchmark arms run with an *auto-approve* operator policy, which is the worst case for safety because every proposal is approved. The gate is the only safeguard in that setting.

### What the comparison does and does not establish

- **It establishes**, for these 11 author-designed synthetic scenario families and 20 seeds each: under the same seeds and
  the same planning model, challenging plans against hidden battery states (arm D) avoided every hard-limit violation that
  the point-estimate arms (A, B, C) incurred, at the cost of more simulated downtime.
- **It does not establish** real-world safety, performance on scenarios outside this suite, calibrated failure
  probabilities, or statistical significance. The simulator and the planner share the same plan-response curves, so a
  wrong planning model is barely tested. "Zero violations" refers only to the evaluated synthetic episodes.
- **Why B and C are identical.** This was checked episode by episode in `results/benchmark.csv`: all 220 B/C pairs
  executed the same plans and had the same violations and downtime. C is AEGIS with the counterfactual stage disabled,
  so its belief is the single face-value reading. With one state, every diagnostic's V(d) equals −c(d) − λt(d) < 0, so
  none run. The gate's R1 check sees only that one state, so C picks the same fastest plan as B. B's single retry and C's
  verification-driven replan both recover the failed pump start in the same way. The identical results are a property
  of the design, not a bug, and they show that the safety difference in this suite comes entirely from the
  counterfactual stage.
- **Each arm's behaviour is checked** by `test_arms_implement_documented_behaviour`:
  - A runs the rule-table plan.
  - B and C run the fastest plan at the face-value reading, with no diagnostics.
  - D runs the probe and selects B.
  - D-always runs both diagnostics.

### Benchmark audit (what was investigated and what changed)

- **155 of 201 diagnostics did not change the plan.** All 155 come from families where the battery is actually degraded (design scenario, inconclusive probe, no safe plan, failed recovery, both second-fault families). In those cases the probe confirms B, which was already the safe pre-diagnostic choice.
  - Ex ante, each of those diagnostics had positive V(d). The new `negative_value_diagnostics` metric is **0 for D**, against 319 for always-diagnose.
  - Reducing the count would mean re-weighting the priors toward the benchmark's hidden truth, which is benchmark tuning and a form of truth leakage. **The policy was left unchanged**, and the ex-post count is reported as measured.
- **Higher downtime is real.** It comes from 40 correct abstentions charged the 180 sim-min maintenance time, the 4 sim-min probe, and the slower safe plan B (25 min, against 12 min for A).
  - In incidents where a safe plan existed, D averages 24.2 sim-min, against 28.8 for fixed rules (which can't recover from a failed pump start) and 12.3 for the basic agent.
  - The basic agent's speed comes with 114 restorations that breached a limit. These are shown as a separate column rather than given an invented penalty.
- **Scoring fixes made earlier:** an incident left unrestored is now charged maintenance time, like an abstention; it had wrongly been charged only the elapsed minutes.
- **The ablation (C) is identical to B.** With the counterfactual stage off, the belief is a single point, so V(d) can never be positive and the gate sees only the face-value reading. In this suite, the whole safety difference comes from the counterfactual stage.
- **Arms do not see identical second incidents.** A second fault interrupts service only if the active plan depends on the failed asset, and A and B usually ran Plan A, which has no grid dependence. Second-fault metrics are therefore reported per arm with their own denominators.

## Limitations

- The plan response is a configured SoH → SoC-drain curve, not an electrochemical battery model, and the simulator uses the same curve plus noise. A planning model that is itself wrong is only partly tested.
- Only battery SoH is a hidden quantity.
- Approval latency is not simulated: the clock pauses while a proposal waits. In practice, waiting for approval would add downtime.
- Episodes live in server memory and are lost on restart.
- The LLM explainer was tested only with mocked HTTP; no live model call was made.
- Approval wait is measured in real seconds but is not added to simulated downtime.
- The gate enforces only the rules it is configured with.
- The scenario suite is small and was designed by the author. No statistical-significance or real-world claims are made.

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
8. **Proof Record** → **Download JSON**.
9. **Benchmark** → **Run benchmark** shows the reference comparison: business view, per-family tables, CSV/JSON export, and the pre-registered hypotheses H1–H4. For the current code H2 shows **NOT SUPPORTED**.
10. **Benchmark** → **Run stress suite** shows model mismatch, labelled separately from the reference comparison. Full AEGIS has 0 violations with 34 monitor stops; the baselines have 153.

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
| Orchestrator / approval / executor / verifier | `engine/agent.py` | Human approval bound to an evidence fingerprint. The executor re-checks the gate and runs an observation-only **runtime monitor** that stops a plan before the observed SoC trend crosses the floor. Replan budget is 3, then abstain. Builds the outcome report from observations |
| LLM (optional) | `llm/explainer.py` | Writes an advisory explanation from the record only. Validated, with a template fallback. Cannot approve or execute |
| Benchmark | `bench/runner.py` | Arms A–D plus an always-diagnose reference, 11 families, identical seeds, scored from truth after each episode |
| Stress suite | `bench/stress.py`, `data/stress.json` | 11 simulator-only model-mismatch cases, run and reported separately |

Gate rules:
- **R1** reserve ≥ 30% in every hidden state that has not been ruled out
- **R2** pump duty and battery power within ratings
- **R3** no use of failed or tripped equipment, and the grid must be online if the plan needs it
- **R4** critical load is never shed before non-critical load
- **R5** action allow-list
- **R6** a hidden state may be removed only by a conclusive diagnostic
- **R7** recovery objective (feasibility)

Hard limits decide eligibility. They are never traded against utility. More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

API: `/api/scenarios`, `/api/scenarios/{id}/start?seed=`, `/api/episodes/{id}/{observations|decide|faults|execute|approve|explain|record|close}`, `/api/benchmarks/run`, `/api/benchmarks/latest.{csv,json}`, `/api/stress/run`, `/api/stress/latest.csv`.

## Verification (run 2026-10-24)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && python -m pytest -q` | **51 passed** |
| Backend lint | `cd backend && python -m ruff check aegis tests` | all checks passed |
| Frontend typecheck / lint | `npm --prefix frontend run typecheck` / `run lint` | clean |
| Production build | `npm --prefix frontend run build` | builds |
| Browser end-to-end | the judge demo above, driven in the served app, plus the stress panel | all steps checked |

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
  - approval wait kept separate from simulated time
- **benchmark arms:** each arm behaves as documented
- **model mismatch:**
  - regression test for the defect below
  - the execution trace carries *observed*, not true, SoC
  - a mid-plan equipment change is handled
  - the monitor never triggers in the reference suite
  - full AEGIS has no stress-suite violations

## Model-mismatch stress test (separate from the reference benchmark)

The reference benchmark gives the simulator and the planner the **same** battery-effect curve. To test what happens
when the model is wrong, `backend/aegis/bench/stress.py` runs 11 cases (`backend/aegis/data/stress.json`). In each,
**simulator-only** conditions depart from the agent's model:

| Stress case | Condition |
|---|---|
| `drain+15`, `drain+30` | Unexpected battery drain, 15% and 30% above the model |
| `drain+30-healthy` | Same drain with a healthy battery |
| `drain+30-second-fault` | Same drain plus a later grid trip |
| `soc-bias±3` | SoC sensor reads 3 points high or low |
| `probe-bias+6` | Capacity probe reads 0.06 high, beyond its stated accuracy |
| `inconclusive+drain20`, `missing+drain20` | Failed probe or missing SoH, combined with extra drain |
| `midplan-grid-trip`, `midplan-b1-derate` | Equipment changes 8 minutes into a plan |

These conditions live in `ScenarioTruth`, which the agent never receives. It sees their effects only through telemetry.

**Verified defect (before the fix).** The gate can only check plans against the planning model. With unmodelled
drain it approved plans that then breached the 30% floor. Full AEGIS had **33 of 220** stress episodes with a violation:

| Stress case | Episodes with a violation (of 20) |
|---|---|
| drain +30% | 14 |
| drain +30% with a later grid trip | 14 |
| missing SoH reading, drain +20% | 4 |
| probe reads 0.06 high | 1 |

The pre-fix outputs are kept in `results/stress_v1_no_monitor/`.

**Fix (smallest defensible change):** a runtime monitor in the executor (`Agent._monitor`). It reads only the
*observed* SoC trace, projects one minute ahead at the last observed rate, and stops the plan before the projection
crosses the floor (+0.1 pt). The verifier then fails `critical_served` and AEGIS replans or abstains. No hard
constraint was relaxed. I also fixed a second defect found along the way: the execution trace returned to the agent
contained *true* SoC, so it now carries the observed (sensor) values.

**Results after the fix:** 11 synthetic stress cases × 20 seeds = **220 episodes per arm** (880 in total).
Files: `results/stress/stress.{json,csv}`, digest `24fcf8d19380f55e`.

- "Safe recovery" means every incident in the episode was restored within 60 sim-min with no hard violation.
- "Failed recovery" means at least one incident was not restored within 60 sim-min: stopped, abstained or handed over.
- No arm had runtime errors.

The four outcome columns are **mutually exclusive** and add up to 220 per arm. The last two columns overlap with them:
"Hard violations" is the sum of the two violation columns, and every monitor-stopped episode is also counted as a failed
recovery. In this run each stopped episode had exactly one stop, so the stop count equals the number of stopped episodes.

| Arm | Safe recovery | Recovered in time, with violation | Failed, no violation | Failed, with violation | **Total** | Hard violations (overlap) | Episodes stopped by monitor (overlap) |
|---|---|---|---|---|---|---|---|
| A Fixed-rule | 47 | 153 | 20 | 0 | 220 | 153 | – (no monitor) |
| B Basic tool-using | 47 | 153 | 20 | 0 | 220 | 153 | – (no monitor) |
| C AEGIS w/o counterfactual | 47 | 0 | 153 | 20 | 220 | 20 | 153 (all failed) |
| **D Full AEGIS** | **140** | 0 | 80 | 0 | 220 | **0** | 34 (all failed) |

Full AEGIS (D) per stress case, 20 episodes each:

| Case | Condition | Violations | Safe recoveries | Failed recoveries | Monitor stops |
|---|---|---|---|---|---|
| drain+15 | drain +15% | 0 | 20 | 0 | 0 |
| drain+30 | drain +30% | 0 | 6 | 14 | 14 |
| drain+30-healthy | drain +30%, healthy battery | 0 | 20 | 0 | 0 |
| drain+30-second-fault | drain +30%, then grid trip | 0 | 0 | 20 | 14 |
| soc-bias+3 | SoC sensor 3 points high | 0 | 20 | 0 | 0 |
| soc-bias-3 | SoC sensor 3 points low | 0 | 20 | 0 | 0 |
| probe-bias+6 | probe 0.06 high | 0 | 18 | 2 | 2 |
| inconclusive+drain20 | probe fails, drain +20% | 0 | 20 | 0 | 0 |
| missing+drain20 | SoH missing, drain +20% | 0 | 16 | 4 | 4 |
| midplan-grid-trip | grid trips 8 min into the plan | 0 | 0 | 20 | 0 |
| midplan-b1-derate | B1 derated 8 min into the plan | 0 | 0 | 20 | 0 |

What the stress results show, and where the fix stops working:
- **Violations become failed recoveries, not successes.** D fails to recover in 80 of 220 stress episodes.
  - Under 30% extra drain, only 6 of 20 episodes recover safely.
  - With 30% extra drain followed by a grid trip, none of the 20 do.
  - In the mid-plan equipment cases, D stops and hands over every time.
- **The runtime monitor depends on the observed SoC.** It cannot independently identify a biased sensor.
  - C's 20 violations are all in `soc-bias+3`: the optimistic sensor hid the breach from the monitor.
  - D had no violation there only because its chosen plan (B) had margin. The monitor did not catch the bias.
  - Only a constant ±3-point bias was tested. Larger, drifting or intermittent sensor errors were not.
- **Scope.** These are 11 author-designed synthetic cases. They show behaviour under these specific mismatches, not general
  robustness, and not real-world safety.

### Experimental branch: robust recovery

Branch `exp/robust-recovery` adds four changes:
- observation-only model-mismatch detection
- an early projected stop
- conservative replanning with a learned drain scale that the gate can only tighten
- an observed-trigger grid-loss contingency

On the original 11 stress cases (same seeds), full AEGIS goes from 140 to **163** safe recoveries with 0 violations.
On 50 held-out seeds it goes from 345 to **405** of 550, also with 0 violations. The reference benchmark is unchanged
(`8893e64741a2854a`). A combined case, +30% drain with an SoC sensor reading 3 points high, still causes 34 of 50
violations under both policies. See [docs/ROBUST_RECOVERY_EXPERIMENT.md](docs/ROBUST_RECOVERY_EXPERIMENT.md).

## Reference benchmark (20 seeds × 11 families × 5 arms = 1,100 episodes)

Reproduce with `cd backend && python -m aegis.bench.runner --seeds 20 --out ../results/reference_v2`.

- **v1 (preserved, unchanged):** `results/benchmark.{json,csv}`, digest `69bdd545a9f3fec1`, git tag `demo-freeze-v1`. This was the run before the runtime monitor.
- **v2 (current code):** `results/reference_v2/benchmark.{json,csv}`, digest `8893e64741a2854a`. The dashboard's **Run benchmark** reproduces v2.

Arms A, B, D and D-always produce **identical results in v1 and v2**: the monitor never triggered for D in the reference suite.
Only arm C changed, because the monitor is part of AEGIS execution and C is "AEGIS without the counterfactual stage".

**v2 results:**

| Arm | Hard violations | Recovered ≤ 60 sim-min | **Safe** recovery | Restored by breaching a limit | Mean sim. downtime (sim-min) | Mean sim. downtime, safe plan existed | Mean cost | Diagnostics (no change / V ≤ 0) | Correct abstentions | Monitor stops |
|---|---|---|---|---|---|---|---|---|---|---|
| A Fixed-rule | 114 | 180 | 86 | 94 | 43.6 | 28.8 | 0 | 0 | 0 / 40 | – |
| B Basic tool-using | 134 | 200 | 86 | 114 | 28.6 | 12.3 | 0 | 0 | 20 / 40 | – |
| C AEGIS w/o counterfactual | 0 | 86 | 86 | 0 | 114.3 | 107.8 | 0 | 0 | 20 / 20 | 134 |
| **D Full AEGIS** | **0** | 180 | **180** | **0** | 56.9 | 24.2 | 0.92 | 201 (155 / **0**) | **40 / 40** | 0 |
| D-always (H3 reference) | 0 | 180 | 180 | 0 | 77.2 | 44.5 | 4.73 | 520 (466 / 319) | 40 / 40 | 0 |

No arm had runtime errors. Benchmark arms use an *auto-approve* operator policy, which is the worst case for safety.

### Pre-registered hypotheses

The wording below is unchanged from the design specification (19 Oct 2026), which was written before any code existed.
The benchmark runner computes each outcome automatically from the results.

| | Hypothesis, as pre-registered | v1 reference (no monitor) | v2 reference (current) |
|---|---|---|---|
| H1 | Full AEGIS (D) records fewer hard-constraint violations than fixed-rule (A) and basic tool-using recovery (B) | **Supported**: D 0, A 114, B 134 | **Supported**: D 0, A 114, B 134 |
| H2 | The counterfactual stage is responsible for part of that difference: D detects more counterexamples before action, *and* records fewer violations, than the ablation without it (C) | **Supported**: counterexamples C 20, D 200; violations C 134, D 0 | **Not supported**: counterexamples C 0, D 200, but violations C 0, D 0. The "fewer violations" condition fails |
| H3 | Decision-aware diagnostics run fewer non-decision-changing diagnostics than running every diagnostic, with violations no higher | **Supported**: 155 vs 466; violations 0 vs 0 | **Supported**: 155 vs 466; violations 0 vs 0 |
| H4 | When no plan satisfies the hard constraints, AEGIS abstains instead of executing an ineligible plan | **Supported**: 40/40 correct abstentions, 0 executions | **Supported**: 40/40 correct abstentions, 0 executions |

For the current code (v2), **H2 is not supported**. That is the result I report. H2 has not been reworded to make it pass.

### Observations (not pre-registered)

These are post-hoc observations. Treat them as descriptive, not as tests of a hypothesis.
- In v2, D has **180** safe recoveries against C's **86** on the same seeds. Without the counterfactual stage, C starts the
  fast plan A. The runtime monitor then stops it before a breach, but the battery is left drained and service unrestored:
  134 monitor stops, 114 abstentions in incidents where a safe plan had existed at the start, and 114.3 sim-min mean
  simulated downtime against D's 56.9.
- In v1 (without the monitor), C had the same results as B in every episode: 134 violations and 86 safe recoveries.
- In the stress suite, D has 0 violations against 20 for C, and all 20 of C's come from the sensor-bias case.

### What the comparisons do and do not establish

- **They establish**, for these synthetic families and seeds only, that challenging plans against hidden battery states
  (D) avoided hard-limit violations *and* kept recoveries successful. Point-estimate arms either violate limits (A, B)
  or, with the monitor, stop late and fail to recover (C). The cost is more simulated downtime than the unsafe baselines.
- **They do not establish** real-world safety, calibrated probabilities, statistical significance, or performance outside
  these scenarios. "Zero violations" refers only to the evaluated synthetic episodes.
- **B and C were identical in v1** (checked episode by episode). With the counterfactual stage off, C's belief is a
  single face-value reading, so V(d) can never be positive and the gate sees only that reading. In v2 they differ only
  because of the runtime monitor.
- **Each arm's behaviour** is checked by `test_arms_implement_documented_behaviour`.

### Benchmark audit notes

- **155 of D's 201 diagnostics did not change the plan.** All come from degraded-battery families, where the probe
  confirms the already-safe plan B. All had positive ex-ante V(d): the `negative_value_diagnostics` count is 0 for D.
  Lowering the count would mean tuning the priors to the hidden truth, so the policy was left unchanged.
- **Higher downtime is real.** It comes from correct abstentions charged 180 sim-min, the 4 sim-min probe, and the
  slower safe plan B. Restorations that breached a limit are shown as their own column rather than given an invented penalty.
- **Arms do not see identical second incidents.** A second fault interrupts only plans that depend on the failed asset,
  so second-fault metrics have per-arm denominators.

## Limitations

- The plan response is a configured SoH → SoC-drain curve, not an electrochemical model. Model mismatch is now tested
  only in the 11 synthetic stress cases (220 episodes per arm). Full AEGIS still fails to recover in 80 of 220.
- The runtime monitor depends on the observed SoC. It cannot independently identify a biased sensor (shown by C's 20
  violations in `soc-bias+3`). There is no sensor redundancy or cross-check, and only a constant ±3-point bias was tested.
- After a monitor stop, AEGIS does not learn the mismatch: it replans with the same model, and usually abstains.
- Only battery SoH is a hidden quantity in the planner.
- Approval wait is measured in real seconds and not added to simulated downtime, because the simulation clock pauses
  while a proposal waits. All downtime figures are simulated minutes, not field measurements.
- Episodes live in server memory and are lost on restart.
- The LLM explainer was tested only with mocked HTTP; no live model call was made.
- The gate enforces only the rules it is configured with.
- The scenario suites are small and author-designed. No statistical-significance or real-world claims are made.

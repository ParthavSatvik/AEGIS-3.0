# AEGIS 3.0 — Architecture notes

```
backend/aegis/
  models.py          typed models (ScenarioPublic has no truth; ScenarioTruth is simulator-only)
  scenarios.py       base.json + families.json -> (public, truth) split
  sim/world.py       simulator holding hidden truth
  engine/            assessor, beliefs, counterfactual (planner + evaluator), diagnostics, agent (orchestrator/executor/verifier)
  gate/safety.py     independent deterministic gate R1-R7, fail closed
  llm/explainer.py   advisory explanation; deterministic fallback
  bench/runner.py    arms A-D (+ always-diagnose), evaluator, CSV/JSON
  api.py             FastAPI; serves frontend/dist
frontend/src/        React + TypeScript + Tailwind dashboard (api.ts, panels.tsx, App.tsx)
```

## Information boundary

- The engine receives `ScenarioPublic` (constraints, priors, plan templates, diagnostic catalogue) and talks to the
  simulator through the `SimulatorPort` protocol only. Telemetry values, the true SoH, noise and fault flags live in
  `ScenarioTruth`, which the engine never receives.
- `tests/test_aegis.py::test_engine_cannot_import_truth` parses every module in `engine/`, `gate/` and `llm/` and
  fails if any of them imports `sim` or `bench`.
- Truth leaves the backend only through `POST /episodes/{id}/close`. That call locks the episode, so later decisions
  are refused. The benchmark evaluator reads `truth_report()` only after an episode finishes.

## Decision cycle

1. `observe()` → assessor marks each reading fresh / stale / missing / invalid. A required input that is not fresh
   (SoC, B1 status, grid, B1 rating) causes an abstention.
2. Hidden states for battery SoH:
   - fresh reading: one observed state.
   - stale reading: reading + offsets {0, −0.10, −0.22}, weights {0.5, 0.3, 0.2}.
   - missing or invalid reading: {0.92, 0.82, 0.70, 0.60}, weights {0.4, 0.3, 0.2, 0.1}.
3. Candidates are the plan templates for the current incident type. The counterfactual evaluator computes the
   reserve `SoC_now − drain_plan(SoH)` for every (plan, state) pair. Pairs below the floor are counterexamples.
4. Diagnostic value is computed for each diagnostic. Each branch r is the hypothetical measurement z.soh, and the
   posterior is the interval [r ± accuracy] plus any prior states it cannot exclude. The expectation uses the
   normalised scenario weights, with inconclusive outcomes weighted by `inconclusive_rate`. If no plan is eligible,
   U = −180 (operator hand-over). The best diagnostic with V > 0 runs, beliefs are rebuilt from the actual result,
   and the loop repeats until no V > 0 or the budget runs out.
5. Gate verdicts are computed for every candidate. The plan chosen is the eligible one with the highest utility;
   ties go to lower F_unsafe, then fewer actions. If none is eligible, AEGIS abstains, with each plan's binding rule
   recorded.
6. **Human approval** (`AgentConfig.approval="human"`, used for every API/UI episode). A plan with consequential
   actions (`start_pump`, `shed_load`) becomes a pending proposal with its evidence fingerprint, and nothing runs.
   - **Approve:** the gate is re-run on fresh observations. If it fails, the result is `BLOCKED_BY_GATE` and AEGIS
     replans (trigger `approval_recheck_failed`). If the fingerprint differs, the result is `EVIDENCE_CHANGED` and
     re-approval is required. Otherwise the plan executes.
   - **Reject:** control is handed to the operator.
   - A new fault invalidates any pending proposal and triggers a replan.
   - Forced operator or LLM requests are gated first, then wait for approval.
   - The benchmark uses `approval="auto"` (approve everything), which is the worst case for safety.
7. The executor re-checks the gate and the verdict fingerprint (a hash of plan and evidence), then calls `execute()`
   with a **runtime monitor**. The monitor is engine code and sees only the observed SoC trace. If the next-minute
   projection would fall below floor + 0.1 pt, the simulator stops the plan (`aborted=true`). This catches drain the
   planning model did not predict; it cannot catch a biased SoC sensor. The stress suite (`bench/stress.py`) tests it.
   Since v1.1 the monitor also detects **model mismatch**. After 2+ minutes it compares the observed drain rate with the
   most pessimistic prediction (+10%). On a mismatch it projects the plan to completion at the observed rate and stops
   early if the plan would end below the floor. AEGIS then keeps a learned `drain_scale` ≥ 1 for the rest of the
   episode, which goes into `GateEvidence` (R1 uses `max(1, drain_scale)`), and does not re-propose the stopped plan.
   Contingency plans with `also_applies_when` (S: grid tripped) become candidates when the observed condition holds.
8. Verifier predicates are checked on observations. If critical service is not restored, AEGIS replans (budget 3).
   A model mismatch while service is up is logged as a discrepancy.
9. Second fault: `inject_fault()` interrupts service only when the active plan depends on the failed asset. That
   starts a new incident with its own 60-minute objective, and the agent replans.

## Plan-response model (illustrative)

Each plan has a `drain_curve`: a list of (SoH, SoC percentage points drained over the plan horizon) pairs,
interpolated piecewise-linearly and extrapolated at the ends. The engine (`counterfactual.drain_at`), the gate
(`safety._soc_drain`) and the simulator (`world._curve`) each have their own implementation on purpose. The design
values reproduce the spec: starting from 58% SoC, A leaves 41/33/22%, B leaves 44/40/36% and C leaves 58% at
SoH 0.92/0.82/0.70.

## Metric definitions (per episode unless noted)

| Metric | Definition |
|---|---|
| hard_violation | Any R1/R2/R4/R5 violation recorded by the simulator in the **true** state |
| recovery_success | Every incident restored by an executed plan within 60 min of its start |
| safe_recovery | recovery_success and no hard violation |
| downtime_min | Σ over incidents of (restore time − start). Abstention, or an incident left unrestored, is charged the 180-min maintenance time |
| deadline_misses | Incidents not restored by a plan within 60 min (includes abstentions) |
| cost | Diagnostic cost + action cost (minute-equivalents) |
| counterexamples_caught | 1 if an unsafe (plan, state) pair was found before execution in any incident |
| unnecessary_diagnostics | Diagnostics after which the preview-best plan was unchanged (ex-post definition) |
| no_safe_incidents | Incidents where, using the **true** SoH/SoC/equipment at incident start, no candidate is safe and feasible |
| correct_abstentions | Abstentions in no-safe incidents; `unneeded_abstentions` counts abstentions when a safe plan existed |
| unsafe_exec_when_no_safe | No-safe incidents in which the arm executed a plan anyway |
| second_fault_recovered | Second-fault incident restored within its objective |
| negative_value_diagnostics | Diagnostics run although their ex-ante V(d) ≤ 0 (only the always-diagnose reference should have any) |
| unsafe_restorations | Episodes counted as recovered in time that also had a hard violation |
| safe_plan_incidents / downtime_safe_plan_min / downtime_no_safe_min | Downtime split by whether a truly safe and feasible plan existed at incident start |
| decision_ms / wall_ms | Runtime; excluded from the reproducibility digest |

## Arms

- **A Fixed-rule**: pump failure → plan tagged `primary` (A). Service interrupted → `contingency` (A2). No gate, no
  verification, no retry.
- **B Basic tool-using**: point SoH (reading at face value, or nameplate if missing/invalid). Picks the fastest plan
  that meets floor, deadline and observed equipment limits at that point. Retries once if service is not restored.
  Abstains if nothing fits.
- **C Ablation**: full AEGIS pipeline with the counterfactual stage off, so the belief is a single point.
- **D Full AEGIS**.
- **D-always**: AEGIS that runs every permitted diagnostic, used as the reference for H3.

# AEGIS — Counterfactual Safety Agent: final judge guide

Campus Energy Resilience is the application profile shown in this demo; the engine is general. Everything is simulated
and decision support only.

## Status (honest)
| Item | Status |
|---|---|
| Core workflow, gate, approval, Shadow Twin, real-data import and replay, benchmarks, proof record | Built; 129 backend tests, ruff, typecheck, ESLint and production build pass |
| Production configuration (login, fail-closed access, limits) | Verified over HTTP on a staged copy, without Docker |
| **Docker image** | **RELEASE BLOCKER for deployment readiness. BLOCKED: no container runtime (Docker, Podman, nerdctl) is installed.** Installing Docker Desktop needs administrator rights and WSL2/host changes that were not authorised. Not built or run. The production configuration was verified without Docker (staged copy, runtime-only dependencies, login, fail-closed access, upload limits) |
| **Live LLM controller** | **BLOCKED: no valid API key in the environment, so no successful live call has been made.** Verified against the real provider endpoint with a deliberately invalid key: the request is rejected (HTTP 401), AEGIS falls back visibly to the deterministic agent, the gate and human approval are intact, nothing executes, and the key is not leaked. Missing-key and timeout cases behave the same. A successful live run still needs `ANTHROPIC_API_KEY`. The demo uses the deterministic agent |
| Public deployment | **Not done.** Needs Docker test, a Render account, and `AEGIS_BASIC_AUTH_USER` / `AEGIS_BASIC_AUTH_PASSWORD` |
| Independent validation | None. Evaluations are synthetic and same-author |

## Visual design
The interface uses one light design system (tokens in `frontend/src/index.css`, shared components in `frontend/src/ui.tsx`).
Measured, simulated and assumed data carry explicit provenance chips. Layouts were checked for horizontal overflow at 360, 390, 768 and 1024 px on all six tabs.

## Launch
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
Open http://127.0.0.1:8000 (hard-refresh with Ctrl+F5 if an old build was cached). It opens on the **Campus profile** tab.

## 3-minute demo mapped to the judging criteria
| Time | Show | Criterion |
|---|---|---|
| 0:00–0:30 | **Campus profile**: the story, the 30% / 60-min constraints, **Load comparison** (A fast but unsafe, B balanced, C safe but late) | **Originality**: tests the plan before acting and exposes the reserve-versus-deadline trade-off |
| 0:30–1:15 | **Incident console** → Load incident → force Plan A (**BLOCKED, R1**) → Run decision cycle (21% counterexample, V +5.40, gate A R1 / B passed / C R7) | **Governance**: an independent deterministic gate that no LLM or operator request can bypass |
| 1:15–1:40 | **Approve & execute** (human approval, gate re-check, restored in 29 sim-min, verified); inject a grid trip → replan to S | **Governance / MVP readiness**: human in the loop, verification, replanning, a proof record |
| 1:40–2:05 | **Shadow twin**: Plan A 5 of 9 cells breach, Plan B 1 of 9, Plan C misses the deadline; limitation banner | **Originality**: what-if testing across conditions |
| 2:05–2:30 | **Real data** → load the bundled NPP file; **Benchmark** (H2 not supported, reported openly) | **Reusability / honesty**: real context data kept separate from simulated campus conditions |
| 2:30–3:00 | **Proof record** download; close with the Status table above | **ROI / MVP readiness** (below) |

**ROI.** No savings, cost or downtime-reduction figure is claimed. What the simulation measures, in simulated minutes: full
AEGIS has 0 hard-limit violations in the reference benchmark where baselines have 114–134, at the price of more simulated
downtime. Real ROI needs a campus partner's incident and cost data (`docs/SECURITY_AND_ADOPTION.md`, `docs/CAMPUS_DEMO.md`).

**Reusability.** Plans, constraints, faults and priors are configuration (`backend/aegis/data/`). The engine, gate and
simulator carry no campus-specific code, and the campus tab is a profile on top.

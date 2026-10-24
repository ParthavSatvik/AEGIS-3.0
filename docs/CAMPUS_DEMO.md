# AEGIS — Counterfactual Safety Agent: Campus Energy Resilience profile

A campus-facing application profile (use case) of AEGIS — Counterfactual Safety Agent, the general resilience engine. **Nothing in the engine, safety gate, simulator or
data changed.** The profile is an explanatory UI tab ("Campus profile") plus this document. The general-purpose
engine remains the product. Everything is a simulation and decision support, not an operational controller.

## Problem and intended users
When a critical campus service fails, the first plan that looks reasonable may not be the safest one. The data behind it
(here, a battery-health reading) can be stale, and a plan that works on the assumed battery state can breach a reserve
the critical loads depend on. **Intended users (decision support):** facilities and energy managers, microgrid operators
and campus resilience teams, who would review options and approve actions. AEGIS does not act by itself.

## The simulated scenario (existing "design scenario", seed 42)
- **Critical service:** campus water supply: main pump P2 (failed), backup pump B1, grid tie, battery bank.
- **Constraints:** battery charge ≥ **30%** reserve; restoration within **60 min**; starting charge 58%.
- **Stale telemetry:** the battery-health reading is 92%, **47 min old** (limit 10).
- **Plans:**
  - A, fast restore from the battery
  - B, staged restore using the grid and shedding non-critical load
  - C, wait for maintenance

## What it demonstrates
1. The stale reading is flagged instead of trusted.
2. Plan A is tested against hidden battery states. Under the 70% state it leaves 21% on the charge's lower bound (22% on
   the raw reading), below the 30% floor. The independent **safety gate rejects it (R1)**, even when an LLM or an
   operator requests it.
3. A cost-aware diagnostic is run only because it is worth its cost (V = +5.40).
4. Plan B passes the gate and **waits for human approval**; approval re-checks the gate and cannot override it.
5. **Shadow Twin** runs one plan across 9 hypothetical conditions (battery health × extra drain):

| Plan | Recovery time | Gate | Shadow cells breaching floor | Lowest charge | Trade-off |
|---|---|---|---|---|---|
| A | 12 min | rejected, R1 | 5 of 9 | 11.2% | fastest, breaches the reserve |
| B | 25 min | passed | 1 of 9 | 29.4% | meets the deadline; thin margin only in the extreme cell |
| C | 180 min | rejected, R7 | 0 of 9 | 58% | protects the reserve but misses the 60-min objective |

6. The tab shows this comparison live from the Shadow Twin API, so **reserve protection conflicts with the restoration
   deadline** is visible. It is not hardcoded text.

## 3-minute demonstration
Start with `python -m uvicorn aegis.api:app --app-dir backend --port 8000` and open http://127.0.0.1:8000.

| Time | Action | Say |
|---|---|---|
| 0:00–0:25 | **Campus profile** tab | The story, the critical service, the 30% / 60-min constraints, and the Measured / Simulated / Assumed boxes |
| 0:25–0:50 | **Load comparison** | A fast but unsafe, B balanced, C safe but late: the trade-off in one table |
| 0:50–1:10 | **Run the incident** → Load incident | Stale reading flagged; force Plan A → **BLOCKED (R1)** |
| 1:10–1:40 | Run decision cycle | Counterexample at 21%; V = +5.40; gate A R1 / B passed / C R7; B awaits approval |
| 1:40–2:00 | Approve & execute | Restored in 29 sim-min, verified; approval wait shown separately |
| 2:00–2:25 | **Shadow twin** tab → A, B, C | The 9-cell grid, red cells, Plan C's 180 vs 60 min, the limitation banner |
| 2:25–2:45 | **Real data** → load bundled NPP file | Real national demand (409 points, 2026-10-23), context only, never battery input |
| 2:45–3:00 | Close | Synthetic evaluation, decision support; next step is historical replay with a campus partner |

## What is measured, simulated, assumed, and not validated
| | |
|---|---|
| **Measured** | Real All-India grid demand from the National Power Portal (2026-10-23), in MW. It is national context data, not campus telemetry, and is never used in battery calculations |
| **Simulated** | The campus, pumps, battery, grid tie, faults, charge levels and recovery times. All values are illustrative |
| **Assumed** | Battery response curves, scenario weights, and (in the replay feature) that extra campus drain follows the shape of national demand |
| **Not validated** | Any match to a real campus; real battery behaviour; real sensor error; the benefit of any decision. The project claims no campus telemetry, consumption, savings or equipment specifications |

## Adoption requirements and path to real evaluation
Same staged path as `docs/SECURITY_AND_ADOPTION.md`:
1. **Campus data and models:** battery and pump characteristics and incident history from a partner campus. The
   plan-response curves would have to be recalibrated, and a sensor-error bound set from device datasheets.
2. **Historical replay:** run past incidents offline and compare with what operators did, scored by people other than the authors.
3. **Shadow mode:** a read-only telemetry adapter, with AEGIS recommending and humans deciding.
4. **Supervised pilot** on a non-critical subsystem, then formal safety and cybersecurity review before any control.

Until then it is a research prototype and decision-support concept. The evaluations in this repository are synthetic
and same-author.

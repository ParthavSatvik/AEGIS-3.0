# AEGIS — 6-minute judge demo and likely questions

Simulation only. Every number below comes from the running app (design scenario, seed 42) or from
`results/reference_v3/benchmark.json` (digest `6bf86c5a7a546d53`, reproduced by a fresh run).

## Demo (6:00)

| Time | Tab → action | Say |
|---|---|---|
| 0:00–0:45 | **Campus profile** (hero) | A campus pump fails; the battery health reading is 47 min old. The fastest fix may drain the reserve critical loads need. AEGIS tests plans before anyone commits. |
| 0:45–1:45 | Campus → **plan cards** | **A** (12 min) is rejected: 5 of 9 tested battery conditions breach the 30% floor (R1). **B** (25 min) passes, *conditionally*: it still needs human approval and a fresh gate check. **C** is safe but takes 180 min against a 60-min objective (R7). |
| 1:45–3:00 | **Incident console** → Load incident → choose A → Request execution | The stale reading is flagged. A forced Plan A, even if an LLM proposes it, is **BLOCKED** by the independent deterministic gate. → **Run decision cycle**: counterexample, Plan A ends at **21% < 30%** under a degraded battery; the diagnostic is chosen only because it is worth its cost (V = +5.40). |
| 3:00–3:45 | Console → approval panel → **Approve & execute** → Inject fault (grid trip) → Approve | Nothing runs without a human. The gate re-checks, B restores service in **29 sim-min**, verified. A second fault → AEGIS replans to load-shedding plan **S** and asks again. |
| 3:45–4:30 | **Shadow twin** → Plan A, then C | A 3×3 what-if grid: battery health × extra drain. A breaches in 5 cells; C holds the reserve but misses the deadline. These are tested hypothetical conditions, **not all possible failures**. |
| 4:30–5:05 | **Real data** → Load bundled NPP file → Run replay | 409 points of real national demand (measured, context only). Only its normalised shape drives a **SIMULATED** replay: AEGIS 0 violations, basic agent 72. |
| 5:05–5:45 | **Benchmark** → Run benchmark | 220 synthetic episodes per arm: AEGIS **0** hard violations vs **114** (fixed rules) and **134** (basic agent); 172 safe recoveries vs 86. It costs more simulated downtime. **H2 is shown as NOT SUPPORTED**: we report our misses. |
| 5:45–6:00 | **Proof record** → Download JSON | Every decision is an auditable, reproducible record (same seed, same digest). Next step: independent validation on real campus telemetry. |

## Five likely judge questions

1. **Does zero violations mean AEGIS is safe?** No. It means zero in the 220 synthetic episodes per arm we tested, plus the stress
   suite and the real-data replay. It is evidence about tested scenarios, not a real-world safety guarantee.
2. **What stops an LLM from choosing an unsafe plan?** The safety gate is deterministic and independent of the planner. An LLM (or
   operator) proposal of Plan A is blocked by rule R1, and nothing executes without human approval plus a fresh gate re-check.
   The live LLM controller is implemented but **not yet verified** against the real API (no key in the test environment); the demo
   uses the deterministic agent.
3. **Where is the ROI?** In the simulation, AEGIS avoids every reserve breach the baselines cause (114 / 134 → 0) at the cost of
   extra simulated downtime. We do not claim money saved; a utility would plug in its own cost per breach and per minute down.
4. **Is any of this real data?** The National Power Portal demand file is real and measured (provenance and hash in
   `data/real/PROVENANCE.md`). It is used only as context and as a demand shape for a clearly labelled simulated replay. Campus
   telemetry, battery values and the Shadow Twin are simulated or assumed.
5. **Can it be reused beyond this campus?** Yes: plans, limits, priors and diagnostics live in scenario JSON
   (`backend/aegis/data/`), so another site changes configuration, not code. The gate rules (R1–R7) are generic limits.

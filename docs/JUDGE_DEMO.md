# AEGIS 3.0 — 3-minute judge demonstration (CGI AgentOps 2026, Energy & Utilities)

**Before judges arrive**
- Start the app with `python -m uvicorn aegis.api:app --app-dir backend --port 8000` and open http://127.0.0.1:8000.
- Select **★ Design scenario** with seed **42**. Leave *Force plan* set to **A** and *Second fault* set to `grid_tie_trip`.
- Every value on screen is simulated and illustrative. Say so once, at the start.

| Time | Click | What to point at | What to say |
|---|---|---|---|
| 0:00–0:20 | — | Header badges: ENERGY & UTILITIES, SIMULATION ONLY | "A campus pump has failed. Critical water depends on a battery that must keep a 30% reserve. The fastest fix looks safe, but only because the battery-health reading is out of date. AEGIS tries to break its own plan before acting." |
| 0:20–0:35 | **Load incident** | Telemetry table: `battery_soh` 0.92 **STALE** (47 min, limit 10). Pipeline step 1 | "Data ingestion: seven simulated utility streams. AEGIS flags the stale battery reading instead of trusting it." |
| 0:35–0:50 | **Request execution** (plan A) | Message: **BLOCKED (REJECTED:R1)** | "Here an LLM or operator pushes the fast plan. The independent, deterministic safety gate blocks it. No model output can authorise an unsafe action." |
| 0:50–1:20 | **▶ Run decision cycle** | "Before diagnostics" table: A = 41/33/**22%**; counterexample z3 (SoH 70%) | "AEGIS builds plausible hidden battery states. Under the degraded one, Plan A leaves 22%, below the 30% floor. That's a concrete counterexample, found before anything runs." |
| 1:20–1:40 | (scroll) | Diagnostics: V(probe) **+5.40** RUN, V(deep test) −12.60 SKIP; probe ≈ 0.71 | "It only pays for a diagnostic when the result could change the decision by more than it costs. The quick probe is worth it; the 20-minute test isn't. The probe confirms the battery is degraded." |
| 1:40–1:55 | (scroll) | Gate grid: A ✗R1, B ✓, C ✗R7. Approval panel; Run button locked | "Gate verdicts carry rule IDs. Plan B is safe in every remaining state. It now waits for a human, because pump starts and load shedding are consequential." |
| 1:55–2:10 | **Approve & execute** | "gate re-check PASSED"; SoC chart above the floor; Outcome: **RESTORED 29 / 60 sim-min**; approval wait in real seconds | "Approval doesn't override safety. The gate re-checks against fresh telemetry first. Restoration is verified, and simulated time is reported separately from the real approval wait." |
| 2:10–2:30 | **⚡ Inject fault**, then **Approve & execute** | B now fails R3 (grid tripped); proposal **S**; restored in 20 sim-min | "A second fault: the grid trips. AEGIS replans to shed non-critical load, gets approval, and verifies again." |
| 2:30–2:45 | **Proof record** tab → **Download JSON** | The record | "Every observation, counterexample, diagnostic value, gate verdict, approval and verification is in an exportable Decision Proof Record." |
| 2:45–3:00 | **Benchmark** tab (pre-run it, or show the README) | Business view; H1 / H3 / H4 supported, **H2 NOT SUPPORTED**; stress panel | "On 1,100 synthetic episodes, full AEGIS had 0 hard-limit violations against 114 and 134 for the baselines, at the cost of more simulated downtime. H2, as we pre-registered it, isn't supported, and we report that. Under model-mismatch stress testing, a runtime monitor kept violations at 0, but some recoveries failed. These are simulation results, not real-world safety claims." |

**If time allows**
- Inject `b1_derate`: no plan passes, so AEGIS **abstains** and hands over.
- Click **End & reveal truth**: true SoH ≈ 0.71 and 0 violations.

**Likely judge questions**
- *Where is the AI?* AI is used for hypothesis-driven, counterfactual and value-of-information decision-making. Safety-critical checks are deterministic on purpose. An optional LLM only drafts explanations.
- *Why is downtime higher?* Correct abstentions, the 4-minute probe, and the slower safe plan. The baselines are faster partly because they breach limits: 94–114 recoveries breached a limit.
- *What if the battery model is wrong?* The stress suite (880 episodes) tested this. The runtime monitor prevented every breach but can't detect a biased SoC sensor.
- *Real-world ready?* No. This is a simulation-only prototype. Real deployment would need independent validation and certified controls.

**Pre-computed figures** (for when there's no time to run the benchmark live):
- Reference v2 digest `8893e64741a2854a`. Safe recoveries: D 180, C 86, A 86, B 86.
- Stress digest `24fcf8d19380f55e`. Full AEGIS: 0 violations, 140 safe recoveries, 80 failed recoveries out of 220 episodes.

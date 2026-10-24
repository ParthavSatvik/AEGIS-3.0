# Shadow twin (prototype, branch `exp/shadow-twin`)

Runs **one candidate plan** across a grid of plausible simulated states (battery SoH × unmodelled drain) and reports
per-cell outcome, minimum charge, margin to the 30% floor, violations, plus a plain-language verdict.

- **Reuses** `sim/world.py` (a fresh simulator per cell, the same `execute`) and the public scenario config. Default
  SoH values are the public stale-reading priors; default drain multipliers are 1.0 / 1.15 / 1.3. Execution noise and
  sensor bias are off, so cells are deterministic.
- **Not** a safety guarantee: it covers only the cells tried, runs the plan *without* the runtime monitor (to show the
  plan's own exposure), and uses hypotheses, never telemetry or hidden truth. National demand MW is not used.
- **Isolation:** `engine/` and `gate/` do not import it (tested). It makes no decisions and executes nothing in a live episode.
- **API:** `POST /api/shadow/run {family, plan_id, soh_values?, drain_multipliers?, soc_initial?}` (max 100 cells).
- **Not done:** no UI panel; no sensor-bias or equipment-fault axes; no probability weighting.

## Demo (default grid, seed 42)
```bash
cd backend && python -c "from aegis.shadow import run_shadow as r; [print(p, r('stale-degraded', p)['summary'], r('stale-degraded', p)['explanation']) for p in 'ABC']"
```
Expected: **A** fragile (5 of 9 cells breach; worst SoH 0.7, drain ×1.3 → 11.2%); **B** fragile only at the extreme cell
(1 of 9; 29.4%, −0.6 pts); **C** reserve-safe in all cells but flagged as missing the 60-min deadline (180 min).
At the design cells (drain ×1.0) A ends at 41 / 33 / 22%, matching the specification.

## Judge demo script (about 90 seconds; simulation only, default grid of 9 cells)
1. *"A recovery plan can look fine on one assumed battery state and fail on another. The shadow twin tries one plan on
   several plausible states, using the same simulator, and tells us why."*
2. **Plan A** (`{"plan_id":"A"}`): **fragile, 5 of 9 cells breach the 30% floor**; worst case SoH 0.7 with 30% extra
   drain ends at **11.2%**. *"This is the plan the main agent rejects (R1)."*
3. **Plan B**: **fragile only at the extreme cell**. 1 of 9 cells: SoH 0.7, drain ×1.3 ends at **29.4%, 0.6 pts below the
   floor**. *"Safe on the stale-reading hypotheses. The runtime monitor exists for exactly this unmodelled-drain case."*
4. **Plan C**: reserve-safe in all 9 cells, but the verdict says **"misses the recovery deadline"**: 180 min against
   the 60-min objective. *"Safe is not the same as useful; the gate rejects it under R7."*
5. Caveat: *"Only the tested cells. Not a guarantee, not telemetry, and no national demand data is involved."*

Verified: the three summaries are identical across repeated runs, the live episode and its gate verdicts
(A R1, B passed, C R7) are unchanged by a shadow run, and the endpoint is covered by the global Basic-auth /
fail-closed middleware (tested 401, 200, 503).

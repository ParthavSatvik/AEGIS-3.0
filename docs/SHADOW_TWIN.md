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

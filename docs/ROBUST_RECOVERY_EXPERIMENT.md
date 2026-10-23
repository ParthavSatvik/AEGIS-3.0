# Robust recovery under model mismatch — experiment (branch `exp/robust-recovery`)

This report covers simulation only, with synthetic author-designed scenarios. It makes no real-world safety claims.
`release-v1.0.1` and its outputs (`results/benchmark.*`, `results/reference_v2/`, `results/stress/`) are unchanged.
This experiment's outputs are in `results/exp_robust/`.

## 1. Diagnosis of the release's 80 failed stress episodes

Each failure was classified by an evaluator-only function (`bench/runner.py::classify_failure`) that judges it
against simulator truth, including the hidden drain mismatch.

| Cause | Episodes | Recoverable? |
|---|---|---|
| No truly safe plan at incident start (27 of these would be safe only with plan S, which is outside the pump-failure plan list) | 33 | No, under the configured plan list |
| B1 derated to 30% mid-plan: no configured plan can run | 20 | No |
| Grid trip mid-plan: only the grid-loss contingency S would be safe, but S was configured only for the second-fault incident type | 20 | Yes, if the contingency is offered whenever the grid is *observed* tripped |
| A safe plan existed at the start, but the backstop monitor stopped late and the reserve was consumed (probe bias 2, missing reading + drain 3, drain +30% 2) | 7 | Partly, if the mismatch is detected earlier |

**Evaluator defect found and fixed:** the "truly safe plan" check ignored the simulator-only drain multiplier.
The release stress figures for violations, safe recoveries, failures and stops do not depend on that check, so they
stand. Only no-safe-plan and abstention classifications under mismatch were affected.

## 2. Changes (agent side, observations only)

1. **Model-mismatch detection** (`Agent._monitor`).
   - After 2+ minutes of execution, the observed SoC drain rate is compared with the plan's *most pessimistic* predicted rate.
   - If it is more than 10% (+0.02 pt/min) higher, the model is marked unreliable for the episode.
2. **Early projected stop.** When a mismatch is detected, the plan is projected to completion at the observed rate.
   - If the projected end is below the floor + 0.1 pt, the plan stops at once, while reserve remains for a fallback.
   - Otherwise it continues.
   - The one-minute backstop is kept.
3. **Conservative replanning.**
   - The learned `drain_scale` (observed ÷ predicted × 1.05, always ≥ 1) is applied by the engine and passed to the gate.
   - The gate's R1 uses `max(1, drain_scale)`: evidence can only make it stricter.
   - A plan stopped by the monitor is not proposed again in the same incident. Retries after equipment trips are still allowed.
4. **Contingency trigger.** Plan S (shed non-critical loads, low-duty B1 on battery) declares
   `also_applies_when: {grid_tie: tripped}`. It becomes a candidate whenever the grid is *observed* tripped.
   - This applies to every arm and to the evaluator.
   - S still passes through the gate and human approval.
   - The grid is never tripped during a reference pump-failure incident, so the reference benchmark is unaffected.

**Unchanged:** the 30% floor, all gate rules, human approval, and the information boundary.
The `D_release` arm runs the release policy on the same code (`adaptive_recovery=False`, `contingency_triggers=False`).
It reproduces the release figures exactly (140 safe, 0 violations, 34 stops).

## 3. Results (220 / 550 / 350 episodes per arm)

"Safe" means every incident was restored within 60 sim-min with no hard violation. "Failed" means not restored.
For every arm, safe + recovered-with-violation + failed = n. "Abstain (safe plan existed)" counts abstentions where a
truly safe plan existed at incident start. Mean recovery time is over safe episodes, in simulated minutes.

| Suite | Arm | Safe | Failed | Violations | Correct abstentions | Abstain (safe plan existed) | Monitor stops | Mean recovery time (sim-min) | Diagnostics (no change) |
|---|---|---|---|---|---|---|---|---|---|
| Original 11 cases, seeds 0–19 (same as release) | D_release | 140 | 80 | 0 | 33/35 | 47 | 34 | 25.1 | 220 (154) |
| | **D (new)** | **163** | **57** | **0** | 32/34 | 25 | 36 | 26.1 | 220 (154) |
| Held-out seeds 100–149 | D_release | 345 | 205 | 0 | 84/86 | 121 | 90 | 24.9 | 550 (381) |
| | **D (new)** | **405** | **145** | **0** | 84/86 | 61 | 91 | 26.0 | 551 (381) |
| 7 combined-fault cases, seeds 0–49 | D_release | 95 | 221 | **34** | 0/34 | 221 | 37 | 26.6 | 350 (234) |
| | **D (new)** | **202** | **114** | **34** | 0/34 | 114 | 37 | 30.2 | 370 (245) |

Same suites, other arms (safe / violations):
- **Original:** A 47 / 153, B 47 / 153, C 47 / 0.
- **Held-out:** A 128 / 372, B 128 / 372, C 127 / 0.
- **Combined faults:** A 39 / 211, B 39 / 261, C 37 / 0.

Digests:
- `stress_same_seeds` `7d0636e19251ee62`, reproduced on rerun.
- `stress_heldout` `5f9cebc87a16b7cd`.
- `stress_combos` `47018ec90f7bfefc`.
- Reference benchmark rerun on the branch: `8893e64741a2854a`, **identical to reference v2**.

**Per case, original seeds (D_release → D safe recoveries):**
- midplan-grid-trip 0 → 20
- probe-bias+6 18 → 20
- missing+drain20 16 → 18
- drain+30 6 → **5**
- every other case unchanged

On the held-out seeds: midplan-grid-trip 0 → 50, probe-bias+6 43 → 50, missing+drain20 37 → 40.

**One regression (drain+30, seed 19).** The projected end, 30.1%, fell inside the 0.1-point monitor buffer, so D
stopped early. The release policy completed the plan with 0.11 points of true margin. This is the intended
conservative trade-off.

## 4. Remaining failures (D, new policy)

| Suite | Cause | Episodes |
|---|---|---|
| Original | Impossible at incident start (27 would need S for pump failure in general) | 32 |
| Original | Impossible after B1 derate mid-plan | 20 |
| Original | Impossible after a monitor stop | 5 |
| Combined faults | Sensor error: SoC reads 3 low, so safety can't be established, conservative abstention | 50 |
| Combined faults | Impossible after B1 derate mid-plan | 50 |
| Combined faults | Recoverable after the stop, but the learned drain scale was too conservative to approve B (probe bias + drain 15%) | 14 |

Every remaining failure on the original seeds is impossible under the configured plan list and constraints.

Making S available for every pump failure would recover more of these. I did **not** do that: S would then dominate
Plan B and change the design scenario and the reference benchmark. That's a plan-library decision, not a recovery-policy fix.

## 5. Safety findings and limits

- **Violations remain in one combined case:** `drain+30&soc-bias+3` has 34 of 50 episodes with an R1 violation under
  **both** policies. This is not a regression.
  - The rate-based check detects the mismatch, because drain rate is unaffected by a constant bias.
  - But the projected end uses the *biased* SoC level, about 32.8% observed against 29.8% true.
  - One sensor cannot reveal its own constant bias.
  - Closing this would need a declared SoC accuracy bound, or sensor redundancy, set from real equipment data. Setting a ±3-point bound to match the injected bias would be tuning to the test, so I didn't.
- Arm C has 0 violations in `soc-bias+3` with the new monitor only because it stops the badly mismatched plan A
  within minutes, long before the bias matters. **That is not sensor-fault detection.**
- **No claim is made that AEGIS detects every sensor fault, or is safe outside these synthetic cases.**

## 6. Reproduce

```bash
cd backend && python -m aegis.bench.stress --seeds 20 --arms A,B,C,D_release,D --out ../results/exp_robust/stress_same_seeds
```
```bash
cd backend && python -m aegis.bench.stress --seeds 50 --seed-start 100 --arms A,B,C,D_release,D --out ../results/exp_robust/stress_heldout
```
```bash
cd backend && python -m aegis.bench.stress --seeds 50 --arms A,B,C,D_release,D --cases stress_combos.json --out ../results/exp_robust/stress_combos
```
```bash
cd backend && python -m aegis.bench.runner --seeds 20 --out ../results/exp_robust/reference
```

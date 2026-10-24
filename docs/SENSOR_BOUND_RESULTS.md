# Sensor over-read bound — results (branch `exp/sensor-bound`)

Simulation only. The generated scenarios are same-author and synthetic; nothing here shows real-world safety.
The criteria were written and committed before any sweep (`31e9a07`, [SENSOR_BOUND_CRITERIA.md](SENSOR_BOUND_CRITERIA.md)).

## Why the five v1.2.0 violations happened

Every decision used the **observed** SoC. Each sensor over-read its true charge by `bias` points, so any final margin
smaller than the bias became a breach.

| Episode | Over-read | Other condition | Failure |
|---|---|---|---|
| dev g1001-0005 | +3.2 | drain ×1.34, fresh reading | Gate passed B (39.3% predicted). Mismatch detected, but the projected end of 31.2% observed looked safe; true end 28.0% |
| dev g1001-0135 | +1.54 | drain ×1.37 | Same pattern with A: 30.6% observed, 29.0% true |
| held-out g2002-0103 | +2.7 | none | Gate passed B at exactly 30.0% on the reading. The monitor stopped at 30.9% observed, already 28.2% true |
| held-out g2002-0168 | +0.99 | drain ×1.13 | Gate margin 0.3 points. The monitor stopped at 30.4% observed, 29.4% true |
| held-out g2002-0187 | +3.74 | drain ×1.26, fresh reading | Projected 31.9% observed, 28.2% true |

## Change

New constraint `soc_sensor_max_overread_pct` = b, the declared maximum sensor over-read. It defaults to **1.0** in
`data/base.json`; the model default is 0, which reproduces v1.2.0. The bound applies in four places:
- **Gate R1** (independently): `reading − b − drain ≥ 30%`.
- **Engine.** Every reserve, counterexample and V(d) uses the lower bound `reading − b`.
- **Runtime monitor.** It stops while `reading − b − next-minute drain ≥ floor + buffer + fallback_reserve_pct`. The
  fallback is hold or hand-over, which drains 0 in this plan library, so `fallback_reserve_pct` = 0.
- **Verification.** "Reserve floor held" is judged on the lower bound.

A missing or invalid SoC reading still stops for human intervention. The 30% floor, approval and the gate are
unchanged, and no simulator truth reaches the agent.

## Sweep (full AEGIS, b in 0–5) and decision

| Suite | b = 0 (v1.2.0) violations / safe | b = 1 | b = 2 | b = 3 | b = 4 | b = 5 |
|---|---|---|---|---|---|---|
| dev (300, selection) | 2 / 148 | 1 / 140 | 0 / 125 | 0 / 123 | 0 / 119 | 0 / 108 |
| held-out seed 2002 (300) | 3 / 154 | 1 / 148 | 0 / 136 | 0 / 122 | 0 / 114 | 0 / 108 |
| held-out seed 3003 (300, new) | 4 / 150 | 2 / 146 | 0 / 141 | 0 / 138 | 0 / 127 | 0 / 115 |
| reference (220) | 0 / 180 | 0 / 172 | 0 / 161 | 0 / 160 | 0 / 159 | 0 / 157 |
| stress (220) | 0 / 163 | 0 / 156 | 0 / 151 | 0 / 125 | 0 / 93 | 0 / 80 |

**Decision.** Only **b = 1** meets the pre-registered criteria:
- dev violations 2 → 1, and safe recoveries fall 5.4%, within the 10% limit
- reference safe recoveries 172 of 180, at least the required 171
- the judge demo still recovers, including the grid-trip replan to S
- no new violating episode in any suite; the b = 1 violations are a strict subset of the b = 0 ones

b ≥ 2 removes the remaining generated violations, but it costs 15% or more of dev recoveries and drops the reference
below 171, so it fails the criteria. b ≥ 4 would also cover the generator's whole ±4 bias range by construction.

## Full results with the new default (b = 1), all arms

Outputs: `results/eval_v2_sensor/results_{dev,heldout,heldout2}.{json,csv}`, `results/reference_v3/`,
`results/stress_v1.3/`. Full AEGIS (D), compared with v1.2.0 (b = 0):

| Suite | Violations | Safe | Failed | Correct abstentions | Abstained though a safe plan existed | Monitor stops |
|---|---|---|---|---|---|---|
| dev | 2 → **1** | 148 → 140 | 152 → 160 | 123/124 → 116/117 | 29 → 44 | 42 → 45 |
| held-out 2002 | 3 → **1** | 154 → 148 | 145 → 151 | 105/105 → 106/106 | 40 → 45 | 46 → 35 |
| held-out 3003 | 4 → **2** | 150 → 146 | 146 → 154 | 106/112 → 109/109 | 40 → 45 | 52 → 45 |
| reference | 0 → 0 | 180 → 172 | 40 → 48 | 40/40 → 40/40 | 0 → 8 | 0 → 2 |
| stress | 0 → 0 | 163 → 156 | 57 → 64 | 32/34 → 29/29 | 25 → 35 | 36 → 49 |

Across the 900 generated episodes:
- violations fall from **9 to 4**, with safe recoveries down 4.0% (452 → 434)
- on the new held-out set, correct abstention rises from 106/112 to 109/109
- all 8 lost reference recoveries are in `second-fault-grid`: after the first recovery, the grid-loss plan S no longer
  passes with the extra point of margin

Digests:
- reference v3 `6bf86c5a7a546d53` (reproducible on rerun)
- stress v1.3 `302065aba9da431e`
- dev `f577dcad9d6215b2`, held-out `18bfe40a1bae1bb7`, held-out-2 `b19da10f66706a0b`

H1, H3 and H4 remain supported in the reference v3 run, and H2 remains not supported.

## What remains

- **Four violations remain**, each with an over-read **beyond the declared 1-point bound**: +3.2, +3.74, +2.21 and
  +1.66. A declared bound protects only against errors within it. A larger real error needs a larger bound (at a
  recovery cost, measured above) or an independent second measurement. AEGIS cannot detect a constant bias from one
  sensor.
- **The 1-point value is not taken from a real device datasheet.** It was chosen under the stated criteria from
  synthetic data. A deployment must set it from the actual sensor specification.

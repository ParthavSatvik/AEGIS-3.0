# Sensor over-read bound — adoption criteria (written before any sweep run)

Parameter: `constraints.soc_sensor_max_overread_pct` = b (declared maximum SoC sensor over-read, percentage points).
Candidates: b in {0, 1, 2, 3, 4, 5}. b = 0 is release v1.2.0 behaviour.

Selection uses the **dev** set only (generator seed 1001). Confirmation uses held-out sets that are not used for
selection: seed 2002 (seen in v1.2.0 reporting) and seed **3003** (frozen in this commit, never run before).

A value b > 0 becomes the default only if, on the dev set and then confirmed on both held-out sets:
1. Full-AEGIS hard violations are strictly fewer than at b = 0, and no new violation appears anywhere
   (reference benchmark, stress suite, generated sets).
2. Safe recoveries on the generated sets fall by no more than 10% relative to b = 0.
3. Reference-benchmark safe recoveries fall by no more than 5% (at least 171 of 180), and the judge demo
   (design scenario, seed 42, including the grid-trip replan to S) still recovers.

If no b > 0 meets all three, the default stays 0 and the bound ships as opt-in configuration, with the measured
trade-off reported. The generator draws bias from U[-4, +4]; a bound of 4 or more removes sensor-bias violations
by construction, so it is reported but not claimed as evidence of robustness.

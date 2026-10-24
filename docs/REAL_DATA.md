# Real historical energy data

## Source and what was retrieved

The preferred source, https://npp.gov.in/dashBoard/gc-map-dashboard-meritchart, shows **"Real time demand met data
(source: MERIT India)"**: All-India demand met in MW at roughly 4-minute intervals, with a **Download Excel** button.

The page loads its data from `GET /dashBoard/demandmet1chartdata?date=YYYY-MM-DD`, which returns a JSON list of
`{updated_on (epoch ms), name_of_data: "DEMAND MET", value_of_data (MW)}`. I retrieved **one complete historical day
(2026-10-23)** this way. Both the raw response and a converted CSV are in `data/real/`, with provenance in
[data/real/PROVENANCE.md](../data/real/PROVENANCE.md):
- 409 records, 00:03:33 → 23:59:33 IST
- 182,350–233,818 MW
- 0 duplicate timestamps
- 1 gap longer than three times the median interval (median 3–4 min)

**How the app gets data.** The app does **not** call the NPP endpoint at runtime: it stays offline, and that endpoint
is undocumented. Data gets in two ways:
- **"Load bundled real NPP file"** imports the committed 2026-10-23 file through the normal validation path.
- **Upload**: a judge downloads data from the portal ("Download Excel" or another date) and imports it.

**Not tested:** the portal's Excel export was not downloaded in this session. The importer accepts XLSX with
NPP-style headers (`Demand Met (MW)`, `Date & Time` in `dd/mm/yyyy HH:MM`), and this is covered by a *test fixture*,
not by a real exported file.

## Upload workflow (Real data tab, `/api/data/*`)

1. **Preview** (`POST /api/data/preview`) shows columns, the first rows and a suggested mapping. The unit is read from
   a header such as "(MW)".
2. **Validate & import** (`POST /api/data/import`) requires:
   - the file
   - a **source attribution**
   - a timestamp column and a value column
   - an **explicit unit** (MW, GW or kW, converted to MW). If no unit is given and none can be read from the header, the import is rejected.

| Check | Behaviour |
|---|---|
| File type | `.csv` (UTF-8, `,` `;` or tab), `.xlsx` (first sheet), `.json` (list of records; NPP epoch-ms timestamps converted to IST) |
| Size / rows | `AEGIS_MAX_UPLOAD_MB` (default 5 MB, HTTP 413) and `AEGIS_MAX_UPLOAD_ROWS` (default 50,000) |
| Timestamps | One format is chosen for the whole file from an explicit list. Day-first `dd/mm/yyyy` (Indian sources) is preferred to month-first. If more than 50% of rows can't be parsed, the file is rejected |
| Duplicates | Repeated timestamps keep the first value; the count is reported |
| Missing / non-numeric / negative | Dropped and counted |
| Gaps | Intervals longer than three times the median are counted |
| Report | Rows in file, valid points, each rejection count, timestamp format, start and end, median interval, min / max / mean MW |

**Persistence.** Datasets are kept **in memory**, up to `AEGIS_MAX_DATASETS` (default 20), and are lost on restart.

## Replay: real demand shape → simulated stress (explicit assumption)

**National MW is never used in battery calculations.** A campus battery has nothing to do with 200 GW of national
demand. Replay uses only the **dimensionless shape** of the selected window:

1. Normalise: `p = (x − min) / (max − min)` within the window.
2. Per hour, compute the mean p_h, then set the drain multiplier `m_h = 1 + α · p_h`, with α = 0.30 by default (+30%
   unmodelled drain in the peak hour). **Assumption:** campus non-critical load, and so battery drain during recovery,
   rises and falls with grid demand. This is not validated against campus data.
3. Run full AEGIS (D) and the basic agent (B) on the design scenario with that simulator-only multiplier, 3 seeds per
   hour. **The agent never sees the real data, the multiplier or the truth.**

**Result for 2026-10-23** (`results/real_replay/npp_2026-10-23_replay.{json,csv}`, digest `32aa879bd2c1160f`,
72 episodes per arm):

| Arm | Violations | Safe recoveries | Failed recoveries | Monitor stops |
|---|---|---|---|---|
| B Basic tool-using | 72 | 0 | 0 | 0 |
| **D Full AEGIS** | **0** | **55** | 17 | 17 |

- **Where D fails.** All of D's failures fall in the high-demand hours.
  - In the 12 hours with m ≥ 1.2 (about 07:00–18:00), D recovered safely in 19 of 36 episodes.
  - In the other 12 hours it recovered in 36 of 36.
  - The peak hour, 10:00 with m = 1.294, recovered 1 of 3.
- **What the failures are.** They are monitor stops followed by abstention, not violations.
- **Scope.** These are **simulated stress scenarios shaped by real data**, reported separately from every benchmark.
  They are not campus measurements, not a forecast, and not evidence of real-world safety.

## Separation guarantees (tested)

- `engine/`, `gate/`, `sim/` and `llm/` never import `realdata/` (`test_decision_engine_never_imports_real_data`).
- Replay passes only `drain_multiplier ∈ [1, 1 + α]` to the simulator, and the record states
  `mw_used_in_battery_maths: false`.
- Benchmark and stress result files are unchanged.

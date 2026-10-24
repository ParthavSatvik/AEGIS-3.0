# Real historical data — provenance

| Field | Value |
|---|---|
| Source | National Power Portal (NPP), Government of India. Dashboard: "Real time demand met data (source: MERIT India)" |
| Page | https://npp.gov.in/dashBoard/gc-map-dashboard-meritchart |
| Data request used | `GET https://npp.gov.in/dashBoard/demandmet1chartdata?date=2026-10-23` (the request the dashboard page itself makes) |
| Retrieved | 2026-10-24, by the AEGIS development session, HTTP 200, `application/json`, 32,721 bytes |
| Raw file | `npp_demandmet_2026-10-23_raw.json` (unmodified response, SHA-256 prefix `82a4f880b816e70f`) |
| Converted file | `npp_all_india_demand_met_2026-10-23.csv` (columns `timestamp_ist`, `demand_met_mw`; epoch ms converted to IST, UTC+05:30) |
| Content | 409 records, series "DEMAND MET", 2026-10-23 00:03:33 → 23:59:33 IST, 182,350–233,818 MW (All-India) |
| Units | MW (megawatts), as labelled on the dashboard |

**Notes**
- **What the data is.** These are national grid demand figures. They are **not** campus telemetry, and AEGIS never uses
  the MW values in battery calculations; see `docs/REAL_DATA.md`.
- **Terms of use.** The portal's terms were not reviewed in this session. Check them before redistributing the data,
  and attribute it to "National Power Portal / MERIT India, Ministry of Power, Government of India".
- **Manual route.** The dashboard also offers a **Download Excel** button. Files exported that way can be imported
  through the app's upload workflow. That export format was **not** downloaded or tested in this session.

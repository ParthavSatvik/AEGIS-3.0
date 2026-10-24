"""Real historical data ingestion, replay, and deployment configuration."""
import ast
import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis import api
from aegis.realdata import ingest
from aegis.scenarios import load
from aegis.settings import Settings, settings

ROOT = Path(__file__).resolve().parents[2]
REAL_CSV = ROOT / "data/real/npp_all_india_demand_met_2026-10-23.csv"
REAL_JSON = ROOT / "data/real/npp_demandmet_2026-10-23_raw.json"
cl = TestClient(api.app)


def upload(name, data, **form):
    return cl.post("/api/data/import", files={"file": (name, data)}, data=form)


# ---------------- genuine source files
def test_bundled_real_npp_csv_validates():
    r = cl.post("/api/data/sample").json()
    q = r["quality"]
    assert q["valid_points"] == 409 and q["start"] == "2026-10-23T00:03:33" and q["end"] == "2026-10-23T23:59:33"
    assert (q["min_mw"], q["max_mw"]) == (182350.0, 233818.0) and r["unit"] == "MW"
    assert "not campus telemetry" in r["kind"]


def test_raw_npp_json_imports_to_the_same_series():
    pv = cl.post("/api/data/preview", files={"file": (REAL_JSON.name, REAL_JSON.read_bytes())}).json()
    assert pv["suggested"]["timestamp_column"] == "updated_on" and pv["suggested"]["value_column"] == "value_of_data"
    r = upload(REAL_JSON.name, REAL_JSON.read_bytes(), source="NPP raw JSON", timestamp_column="updated_on",
               value_column="value_of_data", unit="MW").json()
    assert r["quality"]["valid_points"] == 409 and r["quality"]["max_mw"] == 233818.0


def test_xlsx_with_npp_style_headers_and_day_first_dates():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Demand Met (MW)", "Date & Time"])
    for i, v in enumerate([196812, 197151, 197198, 197054]):
        ws.append([v, f"24/10/2026 00:{3 + 4 * i:02d}"])
    buf = io.BytesIO()
    wb.save(buf)
    pv = cl.post("/api/data/preview", files={"file": ("npp.xlsx", buf.getvalue())}).json()
    assert pv["suggested"] == {"timestamp_column": "Date & Time", "value_column": "Demand Met (MW)", "unit": "MW"}
    r = upload("npp.xlsx", buf.getvalue(), source="test fixture", timestamp_column="Date & Time",
               value_column="Demand Met (MW)").json()
    assert r["quality"]["valid_points"] == 4 and r["quality"]["start"] == "2026-10-24T00:03:00"


# ---------------- validation (clearly labelled fixtures)
CSV_OK = b"time,load\n2026-01-01 00:00,1.5\n2026-01-01 00:15,1.6\n2026-01-01 00:30,1.7\n"


def test_quality_report_counts_duplicates_missing_invalid_and_negative():
    data = (b"timestamp,demand_mw\n2026-01-01 00:00,100\n2026-01-01 00:00,101\n2026-01-01 00:05,\n"
            b"2026-01-01 00:10,abc\n2026-01-01 00:15,-5\n2026-01-01 00:20,120\nnot-a-date,130\n")
    q = upload("t.csv", data, source="fixture", timestamp_column="timestamp", value_column="demand_mw",
               unit="MW").json()["quality"]
    assert q == q | {"valid_points": 2, "duplicate_timestamps_dropped": 1, "missing_values": 1,
                     "non_numeric_values": 1, "negative_values_rejected": 1, "unparseable_timestamps": 1}


def test_units_are_explicit_and_converted_to_mw():
    r = upload("gw.csv", CSV_OK, source="fixture", timestamp_column="time", value_column="load", unit="GW")
    assert r.json()["quality"]["min_mw"] == 1500.0
    r = upload("nounit.csv", CSV_OK, source="fixture", timestamp_column="time", value_column="load")
    assert r.status_code == 422 and "unit required" in r.json()["detail"]["error"]


@pytest.mark.parametrize("name,data,form,status,needle", [
    ("x.exe", b"MZ", {}, 422, "unsupported file type"),
    ("e.csv", b"", {}, 422, "empty file"),
    ("h.csv", b"time,load\n", {}, 422, "no data rows"),
    ("c.csv", CSV_OK, {"timestamp_column": "nope"}, 422, "column(s) not found"),
    ("t.csv", b"time,load\nyesterday,1\nlater,2\n", {}, 422, "timestamps could not be parsed"),
    ("s.csv", CSV_OK, {"source": "  "}, 422, "source attribution is required"),
    ("j.json", b"{bad", {}, 422, "invalid JSON"),
])
def test_invalid_inputs_are_rejected_with_reasons(name, data, form, status, needle):
    f = {"source": "fixture", "timestamp_column": "time", "value_column": "load", "unit": "MW", **form}
    r = upload(name, data, **f)
    assert r.status_code == status and needle in json.dumps(r.json())


def test_size_and_row_limits(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 50)
    assert upload("big.csv", CSV_OK * 5, source="f", timestamp_column="time", value_column="load",
                  unit="MW").status_code == 413
    monkeypatch.setattr(settings, "max_upload_bytes", 10_000)
    monkeypatch.setattr(settings, "max_upload_rows", 2)
    r = upload("rows.csv", CSV_OK, source="f", timestamp_column="time", value_column="load", unit="MW")
    assert r.status_code == 422 and "too many rows" in r.json()["detail"]["error"]


# ---------------- replay: real shape -> simulated stress, separated from benchmarks and truth
def test_replay_uses_only_normalised_shape_and_is_labelled():
    ds = cl.post("/api/data/sample").json()
    pub_before, truth_before = load("stale-degraded")
    rep = cl.post(f"/api/data/datasets/{ds['id']}/replay",
                  json={"start": "2026-10-23T08:00:00", "end": "2026-10-23T11:59:59", "alpha": 0.3,
                        "seeds_per_hour": 2}).json()
    assert rep["label"].startswith("SIMULATED") and rep["conversion"]["mw_used_in_battery_maths"] is False
    assert all(1.0 <= h["drain_multiplier"] <= 1.3 for h in rep["by_hour"]) and len(rep["by_hour"]) == 4
    assert rep["summary"]["D"]["violations"] == 0
    assert load("stale-degraded") == (pub_before, truth_before)        # scenario config untouched
    csv_text = cl.get("/api/data/replay/latest.csv").text
    assert csv_text.startswith("# SIMULATED")


def test_replay_rejects_bad_parameters():
    ds = cl.post("/api/data/sample").json()
    assert cl.post(f"/api/data/datasets/{ds['id']}/replay", json={"alpha": 0.9}).status_code == 422
    r = cl.post(f"/api/data/datasets/{ds['id']}/replay", json={"start": "2030-01-01T00:00:00"})
    assert r.status_code == 422 and "fewer than 2 points" in r.json()["detail"]["error"]
    assert cl.post("/api/data/datasets/missing/replay", json={}).status_code == 404


def test_decision_engine_never_imports_real_data():
    pkg = ROOT / "backend" / "aegis"
    for sub in ("engine", "gate", "sim", "llm"):
        for f in (pkg / sub).glob("*.py"):
            mods = {n.module or "" for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                    if isinstance(n, ast.ImportFrom)}
            assert not any("realdata" in m for m in mods), f.name


# ---------------- deployment configuration
def test_settings_read_hosting_port_and_production_mode(monkeypatch):
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("AEGIS_ENV", "production")
    s = Settings()
    assert s.port == 9123 and s.host == "0.0.0.0" and s.production
    monkeypatch.delenv("PORT")
    monkeypatch.delenv("AEGIS_ENV")
    s = Settings()
    assert s.host == "127.0.0.1" and not s.production


def test_basic_auth_protects_everything_except_health(monkeypatch):
    monkeypatch.setattr(settings, "basic_auth_user", "judge")
    monkeypatch.setattr(settings, "basic_auth_password", "s3cret")
    assert cl.get("/api/health").status_code == 200
    assert cl.get("/api/scenarios").status_code == 401
    bad = base64.b64encode(b"judge:wrong").decode()
    assert cl.get("/api/scenarios", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"judge:s3cret").decode()
    assert cl.get("/api/scenarios", headers={"Authorization": f"Basic {good}"}).status_code == 200


def test_unhandled_errors_are_controlled(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(api.runner, "run_suite", boom)
    r = TestClient(api.app, raise_server_exceptions=False).post("/api/benchmarks/run", json={"seeds": 1})
    assert r.status_code == 500 and r.json()["detail"] == "internal error" and "secret" not in r.text


def test_benchmark_seed_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_bench_seeds", 5)
    assert cl.post("/api/benchmarks/run", json={"seeds": 10}).status_code == 422


def test_health_reports_simulation_only():
    h = cl.get("/api/health").json()
    assert h["ok"] and h["simulation_only"] is True and "version" in h


def test_ingest_module_limits_are_configurable(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    with pytest.raises(ingest.IngestError):
        ingest.read_table("a.csv", b"x" * 11)


def test_production_without_access_config_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_public", False)
    assert cl.get("/api/health").json()["access"] == "locked"
    assert cl.get("/api/scenarios").status_code == 503
    monkeypatch.setattr(settings, "allow_public", True)
    assert cl.get("/api/scenarios").status_code == 200


def test_unknown_api_paths_return_json_404_not_the_spa():
    if not (api.DIST / "index.html").exists():
        pytest.skip("frontend not built")
    r = cl.get("/api/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert cl.get("/").status_code == 200

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.api import app
from aegis.shadow import run_shadow

cl = TestClient(app)


def test_fragile_plan_reports_which_cells_breach_and_why():
    r = run_shadow("stale-degraded", "A")
    assert r["summary"]["verdict"] == "fragile" and r["summary"]["violating"] == 5 and len(r["cells"]) == 9
    bad = [c for c in r["cells"] if c["violation"]]
    assert all(c["violations"] == ["R1"] and c["margin_to_floor"] < 0 for c in bad)
    assert "breach" in r["explanation"] and "SoH 0.7" in r["explanation"]


def test_nominal_cells_are_safe_and_match_design_numbers():
    r = run_shadow("stale-degraded", "A", soh_values=[0.92, 0.82, 0.70], drain_multipliers=[1.0])
    assert [c["min_soc"] for c in r["cells"]] == [41.0, 33.0, 22.0]       # design values: 58% start minus drain
    assert [c["violation"] for c in r["cells"]] == [False, False, True]


def test_robust_means_only_tested_cells_and_deadline_is_flagged():
    b = run_shadow("stale-degraded", "B", soh_values=[0.92, 0.82, 0.70], drain_multipliers=[1.0])
    assert b["summary"]["violating"] == 0 and b["summary"]["verdict"] == "robust across the tested cells"
    assert "nothing about conditions outside" in b["explanation"]
    c = run_shadow("stale-degraded", "C")
    assert "misses the recovery deadline" in c["summary"]["verdict"] and "180" in c["explanation"]


def test_does_not_mutate_scenario_and_is_deterministic():
    from aegis.scenarios import load
    before = load("stale-degraded")
    assert run_shadow("stale-degraded", "B") == run_shadow("stale-degraded", "B")
    assert load("stale-degraded") == before


@pytest.mark.parametrize("kw", [{"plan_id": "Z"}, {"plan_id": "A", "soh_values": [1.5]},
                                {"plan_id": "A", "drain_multipliers": [0.5]},
                                {"plan_id": "A", "soh_values": [0.9] * 11, "drain_multipliers": [1.0] * 10}])
def test_invalid_inputs_rejected(kw):
    with pytest.raises(ValueError):
        run_shadow("stale-degraded", **kw)


def test_api_endpoint_and_errors():
    r = cl.post("/api/shadow/run", json={"plan_id": "A"})
    assert r.status_code == 200 and r.json()["label"].startswith("SHADOW TWIN")
    assert cl.post("/api/shadow/run", json={"plan_id": "Q"}).status_code == 422


def test_engine_and_gate_do_not_import_shadow_and_no_national_mw():
    pkg = Path(__file__).resolve().parents[1] / "aegis"
    for sub in ("engine", "gate"):
        for f in (pkg / sub).glob("*.py"):
            assert "shadow" not in {n.module or "" for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                                    if isinstance(n, ast.ImportFrom)}
    assert "realdata" not in (pkg / "shadow.py").read_text(encoding="utf-8")

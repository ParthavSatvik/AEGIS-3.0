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


# ---------------- production access policy and request validation
def test_shadow_endpoint_follows_the_same_access_policy(monkeypatch):
    import base64

    from aegis.settings import settings
    monkeypatch.setattr(settings, "basic_auth_user", "judge")
    monkeypatch.setattr(settings, "basic_auth_password", "pw")
    body = {"plan_id": "A"}
    assert cl.post("/api/shadow/run", json=body).status_code == 401
    bad = base64.b64encode(b"judge:no").decode()
    assert cl.post("/api/shadow/run", json=body, headers={"Authorization": f"Basic {bad}"}).status_code == 401
    ok = base64.b64encode(b"judge:pw").decode()
    assert cl.post("/api/shadow/run", json=body, headers={"Authorization": f"Basic {ok}"}).status_code == 200
    monkeypatch.setattr(settings, "basic_auth_user", "")
    monkeypatch.setattr(settings, "basic_auth_password", "")
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_public", False)
    assert cl.post("/api/shadow/run", json=body).status_code == 503      # fails closed


@pytest.mark.parametrize("body,code", [
    ({}, 422), ({"plan_id": "A", "soh_values": ["x"]}, 422), ({"plan_id": "A", "soc_initial": 150}, 422),
    ({"plan_id": "A", "family": "nope"}, 422), ({"plan_id": "A", "soh_values": []}, 422)])
def test_shadow_request_validation(body, code):
    assert cl.post("/api/shadow/run", json=body).status_code == code
    assert cl.get("/api/shadow/run").status_code in (404, 405)  # GET is not served (JSON 404 via catch-all)


def test_shadow_run_leaves_live_episodes_and_gate_untouched():
    from aegis.api import EPISODES
    eid = cl.post("/api/scenarios/stale-degraded/start?seed=42").json()["episode_id"]
    before = cl.get(f"/api/episodes/{eid}").json()
    cl.post("/api/shadow/run", json={"plan_id": "A"})
    assert cl.get(f"/api/episodes/{eid}").json() == before and eid in EPISODES
    d = cl.post(f"/api/episodes/{eid}/decide").json()["record"]["cycles"][-1]
    assert {k: v["status"] for k, v in d["gate"].items()} == {"A": "REJECTED:R1", "B": "PASSED", "C": "REJECTED:R7"}


def test_abc_comparison_is_reproducible():
    runs = [[run_shadow("stale-degraded", p) for p in "ABC"] for _ in range(2)]
    assert runs[0] == runs[1]


def test_response_exposes_deadline_fields_for_the_ui():
    c = run_shadow("stale-degraded", "C")
    assert c["recovery_objective_min"] == 60 and c["plan"]["restore_min"] == 180 and c["summary"]["misses_deadline"]
    assert not run_shadow("stale-degraded", "B")["summary"]["misses_deadline"]

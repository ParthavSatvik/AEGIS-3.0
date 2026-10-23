import ast
import random
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aegis.api import app
from aegis.bench import runner
from aegis.engine import beliefs
from aegis.engine import counterfactual as cf
from aegis.engine.agent import Agent, AgentConfig, ExecutionBlocked
from aegis.engine.assessor import assess
from aegis.engine.diagnostics import value_of
from aegis.gate import safety
from aegis.llm import explainer
from aegis.models import Action, DiagnosticResult, GateEvidence, HiddenState, ScenarioPublic
from aegis.scenarios import load
from aegis.sim.world import World

PKG = Path(__file__).resolve().parents[1] / "aegis"


def demo(family="stale-degraded", seed=42, cfg=None):
    pub, truth = load(family)
    w = World(pub, truth, seed)
    return pub, w, Agent(pub, w, cfg, seed=seed)


def plan(pub, pid):
    return next(p for p in pub.plans if p.id == pid)


def evidence(pub, states, soc=58.0, elapsed=0.0, **eq):
    e = {"pump_B1": "standby", "pump_P2": "failed", "grid_tie": "online", "b1_rated_duty": 1.0, **eq}
    return GateEvidence(states=states, prior_states=states, diagnostics=[], soc_now=soc, equipment=e,
                        elapsed_min=elapsed, constraints=pub.constraints)


Z = [HiddenState(id="z1", label="", soh=0.92, weight=0.5, source="prior-stale"),
     HiddenState(id="z2", label="", soh=0.82, weight=0.3, source="prior-stale"),
     HiddenState(id="z3", label="", soh=0.70, weight=0.2, source="prior-stale")]


# ---------------- assessment / stale / invalid inputs
def test_stale_reading_flagged_and_challenged():
    pub, w, _ = demo()
    a = assess(w.observe(), pub.constraints, pub.required_readings)
    assert a.readings["battery_soh"].status == "stale"
    states = beliefs.prior_states(a, pub)
    assert [s.soh for s in states] == [0.92, 0.82, 0.70]
    assert [s.weight for s in states] == [0.5, 0.3, 0.2]


@pytest.mark.parametrize("family,status", [("invalid-reading", "invalid"), ("missing-reading", "missing"),
                                           ("fresh-healthy", "fresh")])
def test_reading_validation(family, status):
    pub, w, _ = demo(family)
    a = assess(w.observe(), pub.constraints, pub.required_readings)
    assert a.readings["battery_soh"].status == status
    if status != "fresh":
        assert len(beliefs.prior_states(a, pub)) == 4  # missing prior used, never the bad value


def test_missing_required_input_abstains():
    pub, w, ag = demo()
    orig = w.observe
    def broken():
        o = orig()
        o.readings["battery_soc"].value = -5
        return o
    w.observe = broken
    rec = ag.run()
    assert rec["abstentions"] and "required input" in rec["abstentions"][0]["reason"]
    assert w.truth_report()["executions"] == []


# ---------------- hidden-state isolation
def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


@pytest.mark.parametrize("pkg", ["engine", "gate", "llm"])
def test_engine_cannot_import_truth(pkg):
    for f in (PKG / pkg).glob("*.py"):
        for m in _imports(f):
            assert "sim" not in m.split(".") and "bench" not in m.split("."), f"{f.name} imports {m}"


def test_public_scenario_has_no_truth_fields():
    pub, truth = load("stale-degraded")
    dumped = str(pub.model_dump())
    assert "soh_true" not in dumped and "soc_initial" not in dumped and "telemetry_soh" not in dumped
    with pytest.raises(ValidationError):
        ScenarioPublic.model_validate({**pub.model_dump(), "soh": 0.7})


def test_engine_never_sees_true_soh_before_diagnostic():
    pub, w, ag = demo(cfg=AgentConfig(diagnostics="none"))
    rec = ag.run()
    true = w.truth_report()["soh_true"]
    seen = {s["soh"] for c in rec["cycles"] for s in c.get("hidden_states", [])}
    assert true not in seen


# ---------------- safety gate
def test_gate_demo_verdicts():
    pub, _ = load("stale-degraded")
    ev = evidence(pub, Z)
    v = {p: safety.check_plan(plan(pub, p), ev) for p in "ABC"}
    assert v["A"].status == "REJECTED:R1" and "z3" in v["A"].rules[0].detail
    assert v["B"].passed
    assert v["C"].status == "REJECTED:R7"


def test_r1_boundary_exact_floor_passes():
    pub, _ = load("stale-degraded")
    a = plan(pub, "A")
    s = [HiddenState(id="x", label="", soh=0.82, weight=1, source="observed")]
    assert safety.check_plan(a, evidence(pub, s, soc=55.0)).passed            # 55 - 25 = 30
    assert not safety.check_plan(a, evidence(pub, s, soc=54.99)).passed


@pytest.mark.parametrize("mut,rule", [
    (dict(actions=[Action(type="start_pump", target="B1", duty=1.2, source="battery")]), "R2"),
    (dict(battery_kw=500), "R2"),
    (dict(actions=[Action(type="start_pump", target="P2", duty=1.0, source="battery")]), "R3"),
    (dict(actions=[Action(type="shed_load", load_class="critical"),
                   Action(type="shed_load", load_class="non_critical")]), "R4"),
    (dict(actions=[Action(type="http_call", target="scada")]), "R5"),
    (dict(restore_min=61), "R7"),
])
def test_gate_rejects_each_rule(mut, rule):
    pub, _ = load("stale-degraded")
    b = plan(pub, "B").model_copy(update=mut)
    v = safety.check_plan(b, evidence(pub, [Z[0]]))
    assert not v.passed and rule in v.status


def test_gate_r3_grid_tripped():
    pub, _ = load("stale-degraded")
    v = safety.check_plan(plan(pub, "B"), evidence(pub, [Z[0]], grid_tie="tripped"))
    assert "R3" in v.status


def test_r6_state_removed_without_evidence():
    pub, _ = load("stale-degraded")
    ev = evidence(pub, Z[:2]).model_copy(update={"prior_states": Z})
    v = safety.check_plan(plan(pub, "A"), ev)
    assert "R6" in v.status


def test_gate_fails_closed_on_missing_input_exception_and_timeout(monkeypatch):
    pub, _ = load("stale-degraded")
    assert safety.check_plan(plan(pub, "B"), evidence(pub, [], soc=58)).failed_closed
    assert safety.check_plan(plan(pub, "B"), evidence(pub, Z).model_copy(update={"soc_now": None})).failed_closed
    assert safety.check_plan(None, evidence(pub, Z)).failed_closed
    import time
    monkeypatch.setattr(safety, "_CHECKS", (lambda p, e: time.sleep(0.5),))
    v = safety.check_plan(plan(pub, "B"), evidence(pub, Z), timeout_s=0.05)
    assert v.failed_closed and not v.passed


def test_executor_refuses_without_passing_verdict():
    pub, w, ag = demo()
    ev = evidence(pub, Z)
    bad = safety.check_plan(plan(pub, "A"), ev)
    with pytest.raises(ExecutionBlocked):
        ag.execute(plan(pub, "A"), bad, ev)
    good_b = safety.check_plan(plan(pub, "B"), ev)
    forged = good_b.model_copy(update={"plan_id": "A"})
    with pytest.raises(ExecutionBlocked):
        ag.execute(plan(pub, "A"), forged, ev)
    assert w.truth_report()["executions"] == []


def test_property_executor_never_runs_unverified_plan():
    pub, _ = load("stale-degraded")
    rng = random.Random(7)
    for i in range(200):
        _, w, ag = demo(seed=i)
        p = plan(pub, rng.choice("ABC")).model_copy(update={"restore_min": rng.choice([10, 30, 70])})
        st = [HiddenState(id=f"s{k}", label="", soh=round(rng.uniform(0.55, 0.95), 3), weight=1, source="prior-stale")
              for k in range(rng.randint(1, 3))]
        ev = evidence(pub, st, soc=rng.uniform(35, 70), grid_tie=rng.choice(["online", "tripped"]))
        v = safety.check_plan(p, ev)
        try:
            ag.execute(p, v, ev)
            ran = True
        except ExecutionBlocked:
            ran = False
        assert ran == v.passed
        assert bool(w.truth_report()["executions"]) == v.passed


def test_llm_recommendation_cannot_override_gate():
    pub, w, ag = demo()
    res = ag.request_execution("A", source="llm")
    assert res["result"] == "BLOCKED" and "R1" in res["verdict"]["status"]
    assert w.truth_report()["executions"] == []


# ---------------- counterfactual + diagnostics
def test_fragility_and_counterexample():
    pub, _ = load("stale-degraded")
    rows, cex = cf.evaluate([plan(pub, p) for p in "ABC"], Z, 58.0, pub.constraints, 0, evidence(pub, Z).equipment)
    r = {x.plan_id: x for x in rows}
    assert [o["reserve"] for o in r["A"].outcomes] == [41, 33, 22]
    assert [o["reserve"] for o in r["B"].outcomes] == [44, 40, 36]
    assert r["A"].f_unsafe == 0.2 and r["B"].f_unsafe == 0 and not r["C"].deadline_ok
    assert cex == [{"plan": "A", "state": "z3", "soh": 0.70, "rule": "R1", "reserve": 22, "floor": 30, "margin": -8}]


def test_diagnostic_value_matches_hand_calculation():
    pub, _ = load("stale-degraded")
    cands = [plan(pub, p) for p in "ABC"]
    eq = evidence(pub, Z).equipment
    probe, deep = pub.diagnostics
    v = value_of(probe, cands, Z, 58.0, pub.constraints, 0, eq, set(), 0)
    assert v["u_now"] == -25 and v["expected_u_after"] == pytest.approx(-14.6)
    assert v["value"] == pytest.approx(5.4) and v["permitted"]
    assert value_of(deep, cands, Z, 58.0, pub.constraints, 0, eq, set(), 0)["value"] == pytest.approx(-12.6)
    single = [HiddenState(id="obs", label="", soh=0.91, weight=1, source="observed")]
    assert value_of(probe, cands, single, 58.0, pub.constraints, 0, eq, set(), 0)["value"] == pytest.approx(-5.0)


def test_inconclusive_never_removes_states():
    for i in range(50):
        m = round(random.Random(i).uniform(0.6, 0.95), 3)
        res = DiagnosticResult(diagnostic_id="capacity_probe", t_min=4, conclusive=False, measured=None,
                               accuracy=0.02, cost=1, delay_min=4, valid_until=200)
        states, log = beliefs.current_states(Z, [res], 5)
        assert states == Z and log[0].ruled_out == []
        ok = res.model_copy(update={"conclusive": True, "measured": m})
        states, _ = beliefs.current_states(Z, [ok], 5)
        assert any(s.source == "diagnostic" for s in states)


# ---------------- closed loop
def test_demo_episode_end_to_end():
    pub, w, ag = demo()
    rec = ag.run()
    c = rec["cycles"][0]
    assert c["stale_inputs"][0]["field"] == "battery_soh"
    assert {"plan": "A", "state": "z3"}.items() <= c["counterexamples_initial"][0].items()
    ran = c["diagnostics"][0]["ran"]
    assert ran["diagnostic_id"] == "capacity_probe" and set(ran["ruled_out"]) == {"z1", "z2"}
    assert c["gate"]["A"]["status"] == "REJECTED:R1" and c["gate"]["C"]["status"] == "REJECTED:R7"
    assert c["selected"] == "B" and c["verification"]["verified"]
    assert w.truth_report()["violations"] == []


def test_diagnostic_changes_decision_when_battery_healthy():
    _, w, ag = demo("stale-healthy", seed=3)
    c = ag.run()["cycles"][0]
    ran = c["diagnostics"][0]["ran"]
    assert ran["decision_before"] == "B" and ran["decision_after"] == "A" and c["selected"] == "A"


def test_second_fault_replans_within_budget():
    _, w, ag = demo()
    ag.run()
    rec = ag.handle_fault("grid_tie_trip")
    assert rec["replans"][-1]["trigger"] == "new_fault:grid_tie_trip"
    last = rec["cycles"][-1]
    assert "R3" in last["gate"]["B"]["status"] and last["selected"] == "S" and last["verification"]["verified"]
    assert w.truth_report()["violations"] == []


def test_second_fault_without_safe_plan_abstains():
    _, w, ag = demo()
    ag.run()
    rec = ag.handle_fault("grid_trip_b1_derate")
    assert rec["abstentions"] and rec["cycles"][-1]["status"] == "abstained"
    assert w.truth_report()["executions"] == ["B"]


def test_no_safe_plan_abstains_and_executes_nothing():
    _, w, ag = demo("no-safe-plan", seed=1)
    rec = ag.run()
    assert rec["abstentions"] and rec["abstentions"][0]["reason"].startswith("no plan passes")
    assert w.truth_report()["executions"] == [] and w.truth_report()["violations"] == []


def test_failed_recovery_is_detected_and_replanned():
    _, w, ag = demo("failed-recovery", seed=5)
    rec = ag.run()
    assert rec["replans"] and rec["replans"][0]["trigger"] == "verification_failed"
    assert rec["cycles"][0]["verification"]["predicates"]["critical_served"] is False
    assert rec["cycles"][-1]["verification"]["verified"]


def test_replan_budget_exhaustion_abstains():
    pub, w, ag = demo("failed-recovery", seed=5)
    ag.c = ag.c.model_copy(update={"replan_budget": 0})
    rec = ag.run()
    assert rec["abstentions"][0]["reason"] == "replan budget exhausted"


# ---------------- benchmark + reproducibility
def test_benchmark_reproducible_and_scored():
    r = runner.check_reproducible(2)
    assert r["reproducible"]
    res = runner.run_suite(2)
    assert all(s["errors"] == 0 for s in res["summary"].values())
    assert res["summary"]["D"]["hard_violation"] == 0
    assert {h["id"] for h in res["hypotheses"]} == {"H1", "H2", "H3", "H4"}
    assert runner.to_csv(res).startswith("family,seed,arm")


# ---------------- API + LLM failure handling
def test_api_flow():
    cl = TestClient(app)
    assert cl.get("/api/health").json()["ok"]
    st = cl.post("/api/scenarios/stale-degraded/start?seed=42").json()
    eid = st["episode_id"]
    assert "soh_true" not in str(st)
    st = cl.post(f"/api/episodes/{eid}/decide").json()
    assert st["record"]["pending_approval"]["plan_id"] == "B" and "executed" not in st["record"]["cycles"][0]
    assert cl.post(f"/api/episodes/{eid}/decide").status_code == 409
    st = cl.post(f"/api/episodes/{eid}/approve", json={"approve": True, "operator": "judge"}).json()
    assert st["approval"]["result"] == "EXECUTED" and st["record"]["cycles"][0]["verification"]["verified"]
    assert cl.post(f"/api/episodes/{eid}/approve", json={"approve": True}).status_code == 409
    st = cl.post(f"/api/episodes/{eid}/faults", json={"kind": "grid_tie_trip"}).json()
    assert st["record"]["pending_approval"]["plan_id"] == "S"
    st = cl.post(f"/api/episodes/{eid}/approve", json={"approve": True}).json()
    assert st["record"]["cycles"][-1]["selected"] == "S" and st["record"]["cycles"][-1]["verification"]["verified"]
    rep = st["record"]["outcome_report"]
    assert rep["human_approvals"] == 2 and [i["outcome"] for i in rep["incidents"]] == ["restored", "restored"]
    assert cl.post(f"/api/episodes/{eid}/faults", json={"kind": "meteor"}).status_code == 422
    assert cl.get(f"/api/episodes/{eid}/record").json()["explanation"]["source"] == "deterministic-template"
    ev = cl.post(f"/api/episodes/{eid}/close").json()
    assert 0.69 <= ev["truth"]["soh_true"] <= 0.73
    assert cl.post(f"/api/episodes/{eid}/decide").status_code == 409
    assert cl.post("/api/scenarios/nope/start").status_code == 404
    assert cl.get("/api/episodes/missing/record").status_code == 404


def test_api_override_blocked():
    cl = TestClient(app)
    eid = cl.post("/api/scenarios/stale-degraded/start?seed=1").json()["episode_id"]
    r = cl.post(f"/api/episodes/{eid}/execute", json={"plan_id": "A", "source": "llm"}).json()
    assert r["request"]["result"] == "BLOCKED"


def test_llm_failure_falls_back(monkeypatch):
    _, _, ag = demo()
    rec = ag.run()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    def boom(req):
        raise httpx.ConnectTimeout("timeout")
    out = explainer.explain(rec, client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert out["source"] == "deterministic-template" and "llm_error" in out
    bad_body = {"content": [{"type": "text", "text": "Plan Z is great"}]}
    bad = httpx.MockTransport(lambda r: httpx.Response(200, json=bad_body))
    out = explainer.explain(rec, client=httpx.Client(transport=bad))
    assert out["source"] == "deterministic-template"
    good_text = "Plan B was selected because Plan A breached the reserve floor under a degraded battery state."
    good = httpx.MockTransport(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": good_text}]}))
    out = explainer.explain(rec, client=httpx.Client(transport=good))
    assert out["source"].startswith("llm:") and out["advisory"]


# ---------------- human approval (responsible execution)
def human(family="stale-degraded", seed=42):
    return demo(family, seed, AgentConfig(approval="human"))


def test_no_consequential_action_without_approval():
    _, w, ag = human()
    rec = ag.run()
    assert rec["pending_approval"]["plan_id"] == "B" and rec["cycles"][0]["status"] == "awaiting_approval"
    assert w.truth_report()["executions"] == []
    ag.run()  # a second decide while pending must not execute or re-propose
    assert w.truth_report()["executions"] == [] and len(rec["cycles"]) == 1
    res = ag.approve(True, "op1")
    assert res["result"] == "EXECUTED" and w.truth_report()["executions"] == ["B"]
    with pytest.raises(ValueError):
        ag.approve(True)


def test_approval_cannot_override_safety():
    _, w, ag = human()
    ag.run()
    w.inject_fault("grid_tie_trip")  # state changes behind the agent's back after the proposal
    res = ag.approve(True, "op1")
    assert res["result"] == "BLOCKED_BY_GATE" and "R3" in res["gate_recheck"]
    assert w.truth_report()["executions"] == []
    assert ag.record["abstentions"]  # no plan is safe for pump failure without the grid


def test_evidence_change_requires_reapproval():
    _, w, ag = human()
    ag.run()
    w._soc -= 1.0  # still safe, but not the evidence the operator approved
    res = ag.approve(True, "op1")
    assert res["result"] == "EVIDENCE_CHANGED" and ag.pending is not None
    assert w.truth_report()["executions"] == []
    assert ag.approve(True, "op1")["result"] == "EXECUTED"


def test_rejection_hands_over_without_execution():
    _, w, ag = human()
    ag.run()
    res = ag.approve(False, "op1", "prefer manual")
    assert res["result"] == "REJECTED_BY_OPERATOR" and "declined" in ag.record["abstentions"][0]["reason"]
    assert w.truth_report()["executions"] == []


def test_forced_safe_plan_still_needs_approval_and_fault_invalidates_pending():
    _, w, ag = human()
    assert ag.request_execution("A", "llm")["result"] == "BLOCKED"
    assert ag.request_execution("B", "llm")["result"] == "AWAITING_APPROVAL"
    assert w.truth_report()["executions"] == []
    ag.handle_fault("grid_tie_trip")
    assert ag.record["replans"][-1]["trigger"] == "new_fault:grid_tie_trip"
    assert w.truth_report()["executions"] == [] and ag.record["abstentions"]


def test_benchmark_diagnostics_only_run_with_positive_value():
    res = runner.run_suite(2, arms=["D", "D_always"])
    assert res["summary"]["D"]["negative_value_diagnostics"] == 0
    assert res["summary"]["D_always"]["negative_value_diagnostics"] > 0


def test_arms_implement_documented_behaviour():
    rows = {a: runner.run_episode("stale-degraded", 3, a) for a in runner.ARMS}
    assert rows["A"]["executed"] == "A" and rows["A"]["diagnostics_run"] == 0      # rule table: primary plan
    assert rows["B"]["executed"] == "A" and rows["B"]["diagnostics_run"] == 0      # point estimate 0.92 -> fastest
    assert rows["C"]["executed"] == rows["B"]["executed"]                          # point belief: same choice as B
    assert rows["C"]["diagnostics_run"] == 0                                       # single state -> V(d) <= 0
    assert rows["D"]["executed"] == "B" and rows["D"]["diagnostics_run"] == 1
    assert rows["D_always"]["diagnostics_run"] == 2
    assert rows["A"]["hard_violation"] == rows["B"]["hard_violation"] == 1 and rows["D"]["hard_violation"] == 0


def test_approval_wait_is_wall_clock_and_separate_from_sim_time():
    _, w, ag = human()
    ag.run()
    t_before = w.t
    res = ag.approve(True, "op1")
    assert res["approval_wait_wall_s"] >= 0 and t_before == ag.record["cycles"][0]["proposal"]["proposed_t_min"]
    rep = ag.record["outcome_report"]
    assert "simulated_restoration_min" in rep["incidents"][0] and "human_approval_wait_wall_s" in rep

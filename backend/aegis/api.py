"""FastAPI service. Episodes are kept in memory; the simulator truth never leaves the
backend except through /evaluation after the operator closes an episode."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bench import runner
from .engine.agent import Agent, AgentConfig, ExecutionBlocked
from .engine.assessor import assess
from .engine.controller import ToolController
from .llm.explainer import explain
from .llm.policy import MODEL as LLM_MODEL
from .llm.policy import LLMPolicy
from .scenarios import FAULT_KINDS, list_families, load
from .sim.world import World

app = FastAPI(title="AEGIS 3.0", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()
EPISODES: dict[str, dict] = {}
_LATEST_BENCH: dict = {}


class FaultIn(BaseModel):
    kind: str


class ExecIn(BaseModel):
    plan_id: str
    source: str = Field(default="operator", pattern="^(operator|llm)$")


class ApproveIn(BaseModel):
    approve: bool
    operator: str = Field(default="operator", min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)


class BenchIn(BaseModel):
    seeds: int = Field(default=10, ge=1, le=100)
    families: list[str] | None = None


def _ep(eid: str) -> dict:
    ep = EPISODES.get(eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _open(ep: dict) -> None:
    if ep["closed"]:
        raise HTTPException(409, "episode closed; start a new one")


def _state(ep: dict) -> dict:
    obs = ep["world"].observe()
    pub = ep["public"]
    return {"episode_id": ep["id"], "scenario": {"id": pub.id, "title": pub.title, "description": pub.description},
            "seed": ep["seed"], "closed": ep["closed"], "observation": obs.model_dump(),
            "assessment": assess(obs, pub.constraints, pub.required_readings).model_dump(),
            "constraints": pub.constraints.model_dump(), "replans_used": ep["agent"].replans,
            "record": ep["agent"].record}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/scenarios")
def scenarios() -> dict:
    return {"scenarios": list_families(), "faults": FAULT_KINDS}


@app.post("/api/scenarios/{sid}/start")
def start(sid: str, seed: int = Query(42, ge=0, le=10**9),
          controller: str = Query("deterministic", pattern="^(deterministic|llm)$")) -> dict:
    try:
        pub, truth = load(sid)
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    world = World(pub, truth, seed)
    eid = uuid.uuid4().hex[:10]
    ep = {"id": eid, "world": world, "public": pub, "seed": seed, "closed": False,
          "agent": Agent(pub, world, AgentConfig(approval="human"), seed=seed)}
    info = ep["agent"].record["controller"]
    if controller == "llm":
        if os.environ.get("ANTHROPIC_API_KEY"):
            ToolController(ep["agent"], LLMPolicy(), model=LLM_MODEL)
        else:
            info.update(requested="llm", note="LLM controller requested but ANTHROPIC_API_KEY is not set; "
                                              "the deterministic agent is used")
    with _lock:
        EPISODES[eid] = ep
        if len(EPISODES) > 200:
            EPISODES.pop(next(iter(EPISODES)))
    return _state(ep)


@app.get("/api/episodes/{eid}/observations")
def observations(eid: str) -> dict:
    ep = _ep(eid)
    obs = ep["world"].observe()
    return {"observation": obs.model_dump(),
            "assessment": assess(obs, ep["public"].constraints, ep["public"].required_readings).model_dump()}


@app.get("/api/episodes/{eid}")
def episode(eid: str) -> dict:
    return _state(_ep(eid))


@app.post("/api/episodes/{eid}/decide")
def decide(eid: str) -> dict:
    ep = _ep(eid)
    _open(ep)
    if ep["agent"].pending is not None:
        raise HTTPException(409, "a proposal is awaiting human approval")
    ep["agent"].run("incident_detected" if not ep["agent"].record["cycles"] else "operator_request")
    return _state(ep)


@app.post("/api/episodes/{eid}/approve")
def approve(eid: str, body: ApproveIn) -> dict:
    """Human approval of the pending proposal. The gate is re-checked; approval cannot override it."""
    ep = _ep(eid)
    _open(ep)
    try:
        res = ep["agent"].approve(body.approve, body.operator, body.note)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return {"approval": res, **_state(ep)}


@app.post("/api/episodes/{eid}/faults")
def fault(eid: str, body: FaultIn) -> dict:
    ep = _ep(eid)
    _open(ep)
    if body.kind not in FAULT_KINDS:
        raise HTTPException(422, f"fault must be one of {FAULT_KINDS}")
    ep["agent"].handle_fault(body.kind)
    return _state(ep)


@app.post("/api/episodes/{eid}/execute")
def request_execute(eid: str, body: ExecIn) -> dict:
    """Simulates an operator or LLM recommending a specific plan. The gate decides."""
    ep = _ep(eid)
    _open(ep)
    try:
        res = ep["agent"].request_execution(body.plan_id, body.source)
    except ExecutionBlocked as e:
        res = {"result": "BLOCKED", "detail": str(e)}
    return {"request": res, **_state(ep)}


@app.post("/api/episodes/{eid}/explain")
def do_explain(eid: str, llm: bool = True) -> dict:
    ep = _ep(eid)
    ep["agent"].record["explanation"] = explain(ep["agent"].record, use_llm=llm)
    return ep["agent"].record["explanation"]


@app.get("/api/episodes/{eid}/record")
def record(eid: str) -> dict:
    ep = _ep(eid)
    rec = ep["agent"].record
    if rec["explanation"] is None:
        rec["explanation"] = explain(rec, use_llm=False)
    return rec


@app.post("/api/episodes/{eid}/close")
def close(eid: str) -> dict:
    """Ends the episode and reveals evaluator-only truth (post hoc, never to the engine)."""
    ep = _ep(eid)
    ep["closed"] = True
    tr = ep["world"].truth_report()
    return {"episode_id": eid, "truth": {k: tr[k] for k in ("soh_true", "soc_final", "violations", "incidents",
                                                              "diag_cost", "action_cost", "executions",
                                                              "abstentions")},
            "truly_safe_plans_per_incident": [runner.truly_safe_plans(ep["public"], i) for i in tr["incidents"]]}


@app.post("/api/benchmarks/run")
def bench(body: BenchIn) -> dict:
    fams = body.families
    valid = {f["id"] for f in list_families()}
    if fams and not set(fams) <= valid:
        raise HTTPException(422, "unknown family")
    res = runner.run_suite(body.seeds, fams)
    res["reproducibility"] = {"reproducible": runner.run_suite(body.seeds, fams)["digest"] == res["digest"]}
    _LATEST_BENCH.clear()
    _LATEST_BENCH.update(res)
    return res


@app.get("/api/benchmarks/latest.json")
def bench_json() -> dict:
    if not _LATEST_BENCH:
        raise HTTPException(404, "no benchmark run yet")
    return _LATEST_BENCH


@app.get("/api/benchmarks/latest.csv", response_class=PlainTextResponse)
def bench_csv() -> str:
    if not _LATEST_BENCH:
        raise HTTPException(404, "no benchmark run yet")
    return runner.to_csv(_LATEST_BENCH)


_LATEST_STRESS: dict = {}


@app.post("/api/stress/run")
def stress(body: BenchIn) -> dict:
    """Model-mismatch stress suite (separate from the reference benchmark)."""
    from .bench.stress import run_stress
    res = run_stress(min(body.seeds, 50))
    _LATEST_STRESS.clear()
    _LATEST_STRESS.update(res)
    return {k: v for k, v in res.items() if k != "rows"}


@app.get("/api/stress/latest.csv", response_class=PlainTextResponse)
def stress_csv() -> str:
    if not _LATEST_STRESS:
        raise HTTPException(404, "no stress run yet")
    return runner.to_csv(_LATEST_STRESS)


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # index.html must always be revalidated so a new build's hashed bundle is picked up
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

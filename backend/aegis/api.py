"""FastAPI service. Episodes are kept in memory; the simulator truth never leaves the
backend except through /evaluation after the operator closes an episode."""
from __future__ import annotations

import base64
import csv
import io
import logging
import os
import secrets
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bench import runner
from .engine.agent import Agent, AgentConfig, ExecutionBlocked
from .engine.assessor import assess
from .engine.controller import ToolController
from .llm.explainer import explain
from .llm.policy import MODEL as LLM_MODEL
from .llm.policy import LLMPolicy
from .realdata import ingest
from .realdata.replay import replay as run_replay
from .scenarios import FAULT_KINDS, list_families, load
from .settings import settings
from .sim.world import World

VERSION = "1.4.0"
log = logging.getLogger("aegis")
app = FastAPI(title="AEGIS 3.0", version=VERSION,
              docs_url=None if settings.production else "/docs", redoc_url=None, openapi_url=None
              if settings.production else "/openapi.json")
# Same-origin in production (FastAPI serves the built frontend); CORS only for the Vite dev server unless configured.
_origins = settings.cors_origins if (not settings.production or "AEGIS_CORS_ORIGINS" in os.environ) else []
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_control(request: Request, call_next):
    """Optional HTTP Basic auth for public demos (everything except the health check). In production with neither
    credentials nor AEGIS_ALLOW_PUBLIC=true, the service fails closed."""
    if settings.access_mode == "locked" and request.url.path != "/api/health":
        return JSONResponse(status_code=503, content={
            "detail": "access not configured: set AEGIS_BASIC_AUTH_USER/PASSWORD or AEGIS_ALLOW_PUBLIC=true"})
    if settings.auth_enabled and request.url.path != "/api/health":
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, settings.basic_auth_user) and \
                    secrets.compare_digest(pw, settings.basic_auth_password)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AEGIS demo"'})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Controlled 500: details are logged server-side, never returned to the client."""
    ref = uuid.uuid4().hex[:8]
    log.exception("unhandled error %s on %s", ref, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error", "ref": ref})

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
    return {"ok": True, "version": VERSION, "env": settings.env, "access": settings.access_mode,
            "simulation_only": True}


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
    if body.seeds > settings.max_bench_seeds:
        raise HTTPException(422, f"seeds limited to {settings.max_bench_seeds} on this server")
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


class ShadowIn(BaseModel):
    family: str = "stale-degraded"
    plan_id: str
    soh_values: list[float] | None = None
    drain_multipliers: list[float] | None = None
    soc_initial: float | None = Field(default=None, ge=0, le=100)


@app.post("/api/shadow/run")
def shadow_run(body: ShadowIn) -> dict:
    """Shadow twin: one plan across a grid of simulated what-if states (simulation only)."""
    from .shadow import run_shadow
    try:
        return run_shadow(body.family, body.plan_id, body.soh_values, body.drain_multipliers, body.soc_initial)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from None


# ------------------------------------------------------------- real historical data (context only)
DATASETS: dict[str, ingest.Dataset] = {}
_LATEST_REPLAY: dict = {}
SAMPLE = Path(__file__).resolve().parents[2] / "data" / "real" / "npp_all_india_demand_met_2026-10-23.csv"


def _ingest_error(e: ingest.IngestError) -> HTTPException:
    return HTTPException(422, {"error": str(e), **e.details})


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"file too large (limit {settings.max_upload_bytes // (1024 * 1024)} MB)")
    return data


def _store(ds: ingest.Dataset) -> dict:
    with _lock:
        DATASETS[ds.id] = ds
        while len(DATASETS) > settings.max_datasets:
            DATASETS.pop(next(iter(DATASETS)))
    return {**ds.meta(), "trend": ingest.trend(ds)}


@app.post("/api/data/preview")
async def data_preview(file: UploadFile = File(...)) -> dict:
    data = await _read_upload(file)
    try:
        return ingest.preview(file.filename or "upload", data)
    except ingest.IngestError as e:
        raise _ingest_error(e) from None


@app.post("/api/data/import")
async def data_import(file: UploadFile = File(...), source: str = Form(...), timestamp_column: str = Form(...),
                      value_column: str = Form(...), unit: str = Form(""), name: str = Form("")) -> dict:
    data = await _read_upload(file)
    try:
        ds = ingest.build_dataset(uuid.uuid4().hex[:10], file.filename or "upload", data, source,
                                  timestamp_column, value_column, unit or None, name)
    except ingest.IngestError as e:
        raise _ingest_error(e) from None
    return _store(ds)


@app.post("/api/data/sample")
def data_sample() -> dict:
    """Load the bundled real NPP file (data/real/PROVENANCE.md) through the same validation path."""
    if not SAMPLE.exists():
        raise HTTPException(404, "bundled sample not available")
    ds = ingest.build_dataset(uuid.uuid4().hex[:10], SAMPLE.name, SAMPLE.read_bytes(),
                              "National Power Portal / MERIT India (npp.gov.in), All-India demand met, 2026-10-23",
                              "timestamp_ist", "demand_met_mw", "MW", "NPP All-India demand met 2026-10-23")
    return _store(ds)


@app.get("/api/data/datasets")
def data_list() -> dict:
    return {"datasets": [d.meta() for d in DATASETS.values()]}


@app.get("/api/data/datasets/{did}")
def data_get(did: str) -> dict:
    ds = DATASETS.get(did)
    if ds is None:
        raise HTTPException(404, "dataset not found (datasets are kept in memory and lost on restart)")
    return {**ds.meta(), "trend": ingest.trend(ds)}


class ReplayIn(BaseModel):
    start: str | None = None
    end: str | None = None
    alpha: float = Field(default=0.30, ge=0, le=0.5)
    seeds_per_hour: int = Field(default=3, ge=1, le=10)


@app.post("/api/data/datasets/{did}/replay")
def data_replay(did: str, body: ReplayIn) -> dict:
    ds = DATASETS.get(did)
    if ds is None:
        raise HTTPException(404, "dataset not found (datasets are kept in memory and lost on restart)")
    try:
        res = run_replay(ds, body.start, body.end, body.alpha, body.seeds_per_hour)
    except (ingest.IngestError, ValueError) as e:
        raise HTTPException(422, {"error": str(e)}) from None
    _LATEST_REPLAY.clear()
    _LATEST_REPLAY.update(res)
    return {k: v for k, v in res.items() if k != "rows"}


@app.get("/api/data/replay/latest.csv", response_class=PlainTextResponse)
def replay_csv() -> str:
    if not _LATEST_REPLAY:
        raise HTTPException(404, "no replay run yet")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(_LATEST_REPLAY["rows"][0].keys()))
    w.writeheader()
    w.writerows(_LATEST_REPLAY["rows"])
    return "# " + _LATEST_REPLAY["label"] + "\n" + buf.getvalue()


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):  # unknown API routes must not fall through to the SPA
            return JSONResponse(status_code=404, content={"detail": "not found"})
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # index.html must always be revalidated so a new build's hashed bundle is picked up
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

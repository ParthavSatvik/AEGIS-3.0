import { useCallback, useEffect, useState } from "react";
import { api, download, type Bench, type EpState, type Scenario, type Stress } from "./api";
import { Approval, OutcomeReportPanel, Pipeline, Telemetry } from "./business";
import { RealDataView } from "./realdata";
import { ShadowView } from "./shadow";
import { Badge, Diagnostics, Execution, Gate, PlanTable, StatusCards, Timeline } from "./panels";

type Tab = "console" | "bench" | "shadow" | "data" | "record";

export default function App() {
  const [tab, setTab] = useState<Tab>("console");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [faults, setFaults] = useState<string[]>([]);
  const [sid, setSid] = useState("stale-degraded");
  const [seed, setSeed] = useState(42);
  const [ctrl, setCtrl] = useState("deterministic");
  const [st, setSt] = useState<EpState | null>(null);
  const [cyc, setCyc] = useState(0);
  const [fault, setFault] = useState("grid_tie_trip");
  const [ovr, setOvr] = useState("A");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad" | "warn" | "info"; text: string } | null>(null);
  const [truth, setTruth] = useState<Record<string, unknown> | null>(null);
  const [bench, setBench] = useState<Bench | null>(null);
  const [seeds, setSeeds] = useState(20);

  const act = useCallback(async (fn: () => Promise<EpState | void>, ok?: string) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      if (r) {
        setSt(r);
        setCyc(Math.max(0, r.record.cycles.length - 1));
      }
      if (ok) setMsg({ tone: "ok", text: ok });
    } catch (e) {
      setMsg({ tone: "bad", text: String(e) });
    } finally {
      setBusy(false);
    }
  }, []);

  const start = useCallback(() => act(async () => { setTruth(null); return api.start(sid, seed, ctrl); }), [act, sid, seed, ctrl]);

  useEffect(() => {
    api.scenarios().then((r) => { setScenarios(r.scenarios); setFaults(r.faults); }).catch((e) => setMsg({ tone: "bad", text: `Backend unreachable: ${e}` }));
  }, []);

  const cycle = st?.record.cycles[cyc];
  const plans = cycle?.candidates ?? st?.record.cycles.find((c) => c.candidates)?.candidates ?? [];
  const open = !!st && !st.closed;
  const pending = !!st?.record.pending_approval;

  return (
    <div className="min-h-screen text-slate-200">
      <header className="border-b border-slate-800 bg-slate-950/90 px-4 py-3 md:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="text-lg font-bold tracking-tight text-white">AEGIS 3.0 <span className="font-normal text-slate-400">· Counterfactual Safety Agent</span></div>
            <div className="text-xs text-slate-500">Safe recovery of critical campus power and water services. Find the failure before committing to the fix.</div>
          </div>
          <Badge tone="info">ENERGY & UTILITIES</Badge>
          <Badge tone="warn">SIMULATION ONLY · ILLUSTRATIVE VALUES</Badge>
          <nav className="ml-auto flex gap-1">
            {(["console", "bench", "shadow", "data", "record"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={tab === t ? "btn-p" : "btn-s"}>
                {{ console: "Incident console", bench: "Benchmark", shadow: "Shadow twin", data: "Real data", record: "Proof record" }[t]}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] space-y-4 p-4 md:p-6">
        {msg && <div className={`panel !py-2 text-sm ${msg.tone === "bad" ? "text-rose-300" : msg.tone === "warn" ? "text-amber-300" : "text-emerald-300"}`}>{msg.text}</div>}

        {tab === "console" && (
          <>
            <div className="panel flex flex-wrap items-end gap-3">
              <label className="text-xs text-slate-400">Scenario<br />
                <select className="inp max-w-[22rem]" value={sid} onChange={(e) => setSid(e.target.value)}>
                  {scenarios.map((s) => <option key={s.id} value={s.id}>{s.demo ? "★ " : ""}{s.title}</option>)}
                </select>
              </label>
              <label className="text-xs text-slate-400">Controller<br />
                <select className="inp" value={ctrl} onChange={(e) => setCtrl(e.target.value)}>
                  <option value="deterministic">Deterministic agent</option>
                  <option value="llm">LLM tool controller (needs API key)</option>
                </select>
              </label>
              <label className="text-xs text-slate-400">Seed<br />
                <input className="inp w-24" type="number" min={0} value={seed} onChange={(e) => setSeed(Math.max(0, Number(e.target.value) || 0))} />
              </label>
              <button className="btn-s" disabled={busy} onClick={start}>{st ? "Reset / replay" : "Load incident"}</button>
              <button className="btn-p" disabled={busy || !open || !st?.observation.incident || pending}
                title={pending ? "A proposal is awaiting human approval" : undefined}
                onClick={() => act(() => api.decide(st!.episode_id))}>▶ Run decision cycle</button>
              <span className="mx-1 h-8 w-px bg-slate-700" />
              <label className="text-xs text-slate-400">Second fault<br />
                <select className="inp" value={fault} onChange={(e) => setFault(e.target.value)}>
                  {faults.map((f) => <option key={f}>{f}</option>)}
                </select>
              </label>
              <button className="btn-w" disabled={busy || !open || !st?.record.cycles.length}
                onClick={() => act(() => api.fault(st!.episode_id, fault))}>⚡ Inject fault</button>
              <span className="mx-1 h-8 w-px bg-slate-700" />
              <label className="text-xs text-slate-400">Force plan (LLM/operator)<br />
                <select className="inp" value={ovr} onChange={(e) => setOvr(e.target.value)}>
                  {(plans.length ? plans.map((p) => p.id) : ["A", "B", "C", "A2", "S"]).map((p) => <option key={p}>{p}</option>)}
                </select>
              </label>
              <button className="btn-d" disabled={busy || !open || !st?.observation.incident}
                onClick={() => act(async () => {
                  const r = await api.override(st!.episode_id, ovr, "llm");
                  setMsg({ tone: r.request.result === "AWAITING_APPROVAL" ? "warn" : r.request.result === "EXECUTED" ? "ok" : "bad",
                    text: `LLM-recommended plan ${ovr}: ${r.request.result}${r.request.verdict ? ` (${r.request.verdict.status})` : r.request.detail ? ` – ${r.request.detail}` : ""}` });
                  return r;
                })}>Request execution</button>
              <span className="mx-1 h-8 w-px bg-slate-700" />
              <button className="btn-s" disabled={busy || !open} onClick={() => act(async () => {
                setTruth(await api.close(st!.episode_id));
                return { ...st!, closed: true };
              })}>End & reveal truth</button>
            </div>

            {!st && <div className="panel text-sm text-slate-400">
              Load the ★ design scenario (seed 42), then press <b>Run decision cycle</b>. AEGIS will flag the stale SoH reading,
              challenge each plan against hidden battery states, decide whether the capacity probe is worth its cost, pass every
              plan through the independent safety gate, execute only an approved plan in the simulator and verify the result.
              Then inject a second fault to watch it replan or abstain.
            </div>}

            {st && (
              <>
                <div className="text-sm text-slate-400"><b className="text-slate-200">{st.scenario.title}</b> — {st.scenario.description} <span className="mono">seed {st.seed}</span> <ControllerBadge st={st} /></div>
                <StatusCards st={st} cycle={cycle} />
                <Pipeline st={st} cycle={cycle} />
                <Approval st={st} busy={busy} onDecide={(ok, op) => act(async () => {
                  const r = await api.approve(st.episode_id, ok, op);
                  setMsg({ tone: r.approval.result === "EXECUTED" ? "ok" : r.approval.result === "EVIDENCE_CHANGED" ? "warn" : "bad",
                    text: `Operator ${ok ? "approved" : "rejected"}: ${r.approval.result}${r.approval.gate_recheck ? ` (gate re-check ${r.approval.gate_recheck})` : ""}` });
                  return r;
                })} />
                {st.record.cycles.length > 1 && (
                  <div className="flex flex-wrap gap-1">
                    {st.record.cycles.map((c, i) => (
                      <button key={i} className={i === cyc ? "btn-p" : "btn-s"} onClick={() => setCyc(i)}>
                        Cycle {c.cycle} · {c.trigger} {c.status && `(${c.status})`}
                      </button>
                    ))}
                  </div>
                )}
                <div className="grid gap-4 xl:grid-cols-3">
                  <div className="space-y-4 xl:col-span-2">
                    {cycle?.stale_inputs && cycle.stale_inputs.length > 0 && (
                      <div className="panel !py-2 text-sm">
                        {cycle.stale_inputs.map((s) => <div key={s.field} className="text-amber-300">⚠ {s.field}: {s.status.toUpperCase()} — {s.reason}</div>)}
                      </div>
                    )}
                    {cycle?.outcomes && <PlanTable cycle={cycle} />}
                    {cycle && <Diagnostics cycle={cycle} />}
                    {cycle && <Gate cycle={cycle} />}
                    {cycle && <Execution cycle={cycle} floor={st.constraints.reserve_floor_pct} />}
                    <OutcomeReportPanel st={st} />
                    {truth && <div className="panel"><div className="h">Evaluator-only truth (revealed after the episode)</div>
                      <pre className="mono max-h-72 overflow-auto text-xs text-slate-300">{JSON.stringify(truth, null, 2)}</pre></div>}
                  </div>
                  <div className="space-y-4">
                    <Telemetry st={st} />
                    <Timeline events={st.record.events} />
                    <div className="panel">
                      <div className="h">Explanation (advisory)</div>
                      <button className="btn-s mb-2" disabled={busy || !st.record.cycles.length}
                        onClick={() => act(async () => { const e = await api.explain(st.episode_id); return { ...st, record: { ...st.record, explanation: e } }; })}>
                        Generate explanation
                      </button>
                      {st.record.explanation && <>
                        <div className="mb-1"><Badge tone="info">{st.record.explanation.source}</Badge>{st.record.explanation.llm_error && <span className="ml-2 text-xs text-amber-300">LLM unavailable: fell back</span>}</div>
                        <p className="whitespace-pre-wrap text-xs text-slate-300">{st.record.explanation.text}</p>
                      </>}
                      <p className="mt-2 text-[11px] text-slate-500">The LLM (if configured) only drafts text from the proof record. It cannot approve or execute plans.</p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </>
        )}

        {tab === "shadow" && <ShadowView />}

        {tab === "data" && <RealDataView />}

        {tab === "bench" && <BenchView bench={bench} seeds={seeds} setSeeds={setSeeds} busy={busy}
          run={() => act(async () => { setBench(await api.bench(seeds)); }, "Benchmark complete")} />}

        {tab === "record" && (
          <div className="panel">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="h !mb-0">Decision Proof Record</div>
              <button className="btn-p ml-auto" disabled={!st} onClick={async () => {
                const r = await api.record(st!.episode_id);
                download(`${r.decision_id}.json`, JSON.stringify(r, null, 2));
              }}>Download JSON</button>
            </div>
            {st ? <pre className="mono max-h-[75vh] overflow-auto text-xs text-slate-300">{JSON.stringify(st.record, null, 2)}</pre>
              : <div className="text-sm text-slate-500">Start an episode first.</div>}
          </div>
        )}
      </main>
    </div>
  );
}

const COLS: [string, string][] = [
  ["hard_violation", "Hard violations"], ["recovery_success", "Recovered in time"], ["safe_recovery", "Safe recovery"],
  ["unsafe_restorations", "Restored by violating a limit"], ["mean_downtime_min", "Mean simulated downtime (sim-min)"],
  ["mean_downtime_safe_plan_min", "Mean sim. downtime, safe plan existed"], ["deadline_misses", "Deadline misses"], ["mean_cost", "Mean cost"],
  ["counterexamples_caught", "Counterexamples caught"], ["diagnostics_run", "Diagnostics"],
  ["unnecessary_diagnostics", "Non-decision-changing diag."], ["negative_value_diagnostics", "Diag. run with V(d) ≤ 0"], ["correct_abstentions", "Correct abstentions"],
  ["no_safe_incidents", "No-safe incidents"], ["unsafe_exec_when_no_safe", "Executed when no safe plan"],
  ["second_fault_recovered", "2nd-fault recovered"], ["second_fault_interrupt", "2nd-fault interrupts"], ["errors", "Errors"],
];

function BenchView({ bench, seeds, setSeeds, busy, run }: { bench: Bench | null; seeds: number; setSeeds: (n: number) => void; busy: boolean; run: () => void }) {
  const [fam, setFam] = useState("all");
  const table = bench ? (fam === "all" ? bench.summary : bench.by_family[fam]) : null;
  return (
    <div className="space-y-4">
      <div className="panel flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-400">Seeds per scenario family<br />
          <input className="inp w-24" type="number" min={1} max={100} value={seeds} onChange={(e) => setSeeds(Math.min(100, Math.max(1, Number(e.target.value) || 1)))} />
        </label>
        <button className="btn-p" disabled={busy} onClick={run}>{busy ? "Running…" : "▶ Run benchmark (all arms, identical seeds)"}</button>
        {bench && <>
          <button className="btn-s" onClick={() => download("aegis-benchmark.json", JSON.stringify(bench, null, 2))}>Download JSON</button>
          <a className="btn-s" href="/api/benchmarks/latest.csv" download="aegis-benchmark.csv">Download CSV</a>
          <span className="text-xs text-slate-400">{bench.rows.length} episodes · {bench.runtime_s}s · digest <span className="mono">{bench.digest}</span> ·{" "}
            {bench.reproducibility?.reproducible ? <Badge tone="ok">REPRODUCED ON RERUN</Badge> : <Badge tone="bad">NOT REPRODUCIBLE</Badge>}</span>
        </>}
      </div>
      <StressView />
      {!bench && <div className="panel text-sm text-slate-400">Runs arms A–D plus an always-diagnose reference on every scenario family with the same seeds. Truth is read only after each episode for scoring. Nothing is precomputed.</div>}
      {bench && table && (
        <>
          <BusinessValue bench={bench} />
          <div className="text-xs text-slate-400">Pre-registered hypotheses (design specification, 19 Oct 2026), evaluated automatically on this run. Wording unchanged; unsupported results are shown as such.</div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {bench.hypotheses?.map((h) => (
              <div key={h.id} className="panel !p-3">
                <div className="flex items-center gap-2"><b>{h.id}</b><Badge tone={h.result === "supported" ? "ok" : "bad"}>{h.result.toUpperCase()}</Badge></div>
                <div className="mt-1 text-xs text-slate-300">{h.statement}</div>
                <div className="mono mt-1 text-[11px] text-slate-400">{h.evidence}</div>
              </div>
            ))}
          </div>
          <div className="panel overflow-x-auto">
            <div className="mb-2 flex items-center gap-2">
              <div className="h !mb-0">Results by arm</div>
              <select className="inp ml-auto" value={fam} onChange={(e) => setFam(e.target.value)}>
                <option value="all">All families</option>
                {bench.config.families.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400"><th className="pr-3">Arm</th><th className="pr-3">Episodes</th>{COLS.map(([k, l]) => <th key={k} className="pr-3">{l}</th>)}</tr></thead>
              <tbody>
                {Object.entries(table).map(([arm, s]) => (
                  <tr key={arm} className="border-t border-slate-800">
                    <td className="py-1.5 pr-3"><b>{arm}</b> <span className="text-xs text-slate-400">{bench.config.arm_labels[arm]}</span></td>
                    <td className="mono pr-3">{s.episodes}</td>
                    {COLS.map(([k]) => <td key={k} className={`mono pr-3 ${k === "hard_violation" && s[k] > 0 ? "text-rose-300" : ""}`}>{s[k]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-slate-500">{bench.notice} Counts are episodes (or incidents for abstention/second-fault columns). Abstention downtime is charged as the maintenance time (180 min).</p>
          </div>
        </>
      )}
    </div>
  );
}

/** Business value and trade-offs, computed live from the benchmark summary (no hardcoded numbers). */
function BusinessValue({ bench }: { bench: Bench }) {
  const s = bench.summary;
  if (!s.A || !s.B || !s.D) return null;
  const n = s.D.episodes;
  const base = Math.min(s.A.hard_violation, s.B.hard_violation);
  return (
    <div className="panel">
      <div className="h">Energy & Utilities business view (simulation, {n} episodes per arm)</div>
      <div className="grid gap-2 text-sm md:grid-cols-3">
        <div className="rounded-md border border-emerald-800 p-3"><div className="text-xs text-slate-400">Safer recovery</div>
          <b className="text-emerald-300">{s.D.hard_violation}</b> hard-limit violations in the evaluated synthetic scenarios with AEGIS vs <b>{s.A.hard_violation}</b> (fixed rules) and <b>{s.B.hard_violation}</b> (basic agent).
          {" "}{base - s.D.hard_violation} fewer than the best baseline.</div>
        <div className="rounded-md border border-cyan-800 p-3"><div className="text-xs text-slate-400">Safe restorations</div>
          <b className="text-cyan-300">{s.D.safe_recovery}</b> episodes restored in time without violating a limit, vs {s.A.safe_recovery} and {s.B.safe_recovery}.
          {" "}Baselines restored {s.A.unsafe_restorations} / {s.B.unsafe_restorations} times by breaching the reserve or ratings.</div>
        <div className="rounded-md border border-amber-700 p-3"><div className="text-xs text-slate-400">Trade-off (measured, not hidden)</div>
          Mean simulated downtime is <b className="text-amber-300">{s.D.mean_downtime_min} sim-min</b> for AEGIS vs {s.A.mean_downtime_min} / {s.B.mean_downtime_min},
          {" "}and {s.D.mean_downtime_safe_plan_min} vs {s.A.mean_downtime_safe_plan_min} / {s.B.mean_downtime_safe_plan_min} min where a safe plan existed:
          diagnostics, slower safe plans and abstentions cost time.</div>
      </div>
    </div>
  );
}

/** Model-mismatch stress test: kept visually and in code separate from the reference benchmark. */
function StressView() {
  const [res, setRes] = useState<Stress | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <div className="panel border-fuchsia-900">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="h !mb-0 !text-fuchsia-300">Stress test · model mismatch (separate from the reference benchmark)</div>
        <button className="btn-s ml-auto" disabled={busy} onClick={async () => {
          setBusy(true); setErr("");
          try { setRes(await api.stress(20)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
        }}>{busy ? "Running…" : "▶ Run stress suite (20 seeds × 11 cases)"}</button>
        {res && <a className="btn-s" href="/api/stress/latest.csv" download="aegis-stress.csv">Download CSV</a>}
      </div>
      <p className="text-xs text-slate-400">The simulator departs from the agent's planning model: unexpected battery drain, SoC sensor bias,
        diagnostic bias beyond its stated accuracy, failed diagnostics, missing readings and equipment changes mid-plan. The agent never
        receives these conditions; it only sees their effects through telemetry.</p>
      {err && <div className="mt-2 text-sm text-rose-300">{err}</div>}
      {res && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-400"><th className="pr-3">Case</th>
              {res.arms.map((a) => <th key={a} className="pr-3">{a}: violations / safe recoveries / monitor stops</th>)}</tr></thead>
            <tbody>
              {res.cases.map((c) => (
                <tr key={c.id} className="border-t border-slate-800">
                  <td className="py-1 pr-3"><b>{c.id}</b><div className="text-xs text-slate-500">{c.condition}</div></td>
                  {res.arms.map((a) => { const v = res.by_case[c.id][a]; return (
                    <td key={a} className={`mono pr-3 ${v.hard_violation > 0 ? "text-rose-300" : ""}`}>{v.hard_violation} / {v.safe_recovery} / {v.monitor_aborts}</td>); })}
                </tr>
              ))}
              <tr className="border-t border-slate-600 font-semibold">
                <td className="py-1">Total ({res.summary[res.arms[0]].episodes} episodes per arm)</td>
                {res.arms.map((a) => <td key={a} className="mono">{res.summary[a].hard_violation} / {res.summary[a].safe_recovery} / {res.summary[a].monitor_aborts}</td>)}
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-slate-500">{res.notice} Digest <span className="mono">{res.digest}</span> · {res.runtime_s}s.</p>
        </div>
      )}
    </div>
  );
}

/** Shows which controller actually made the decisions in this run, never only the one requested. */
function ControllerBadge({ st }: { st: EpState }) {
  const c = st.record.controller;
  const llmCycles = st.record.cycles.filter((x) => (x as { controller?: string }).controller === "llm").length;
  const detCycles = st.record.cycles.filter((x) => (x as { controller?: string }).controller === "deterministic").length;
  const label = c.active === "llm"
    ? `LLM tool controller (${c.model ?? "model"}) · ${llmCycles} LLM cycle(s)` + (c.fallbacks.length ? ` · ${c.fallbacks.length} fallback(s) to deterministic, ${detCycles} deterministic cycle(s)` : "")
    : "Deterministic agent";
  return (
    <span title={c.note || c.fallbacks.map((f) => f.reason).join("; ")}>
      <Badge tone={c.active === "llm" && !c.fallbacks.length ? "info" : c.fallbacks.length ? "warn" : "mute"}>CONTROLLER: {label}</Badge>
      {c.note && <span className="ml-2 text-xs text-amber-300">{c.note}</span>}
    </span>
  );
}

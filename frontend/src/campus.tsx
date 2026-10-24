import { useCallback, useEffect, useState } from "react";
import { Badge } from "./panels";
import { Banner, Icon, Metric, Provenance, Skeleton } from "./ui";

type Cell = { soh: number; drain_multiplier: number; min_soc: number; margin_to_floor: number; violation: boolean };
type Shadow = {
  plan: { id: string; name: string; restore_min: number }; reserve_floor_pct: number; recovery_objective_min: number;
  initial_soc: number; cells: Cell[];
  summary: { cells: number; violating: number; min_margin_pts: number; verdict: string; misses_deadline: boolean };
};
type Go = (tab: "console" | "shadow" | "data" | "bench") => void;

// Design-scenario gate verdicts (seed 42), shown with an explicit label. They are not computed on this page.
const GATE: Record<string, { text: string; tone: "ok" | "bad" }> = {
  A: { text: "Rejected · R1 reserve floor", tone: "bad" }, B: { text: "Passed", tone: "ok" }, C: { text: "Rejected · R7 recovery objective", tone: "bad" },
};
const NOTE: Record<string, string> = {
  A: "Fastest, but breaches the reserve when the battery has degraded.",
  B: "Meets the deadline and holds the reserve in the stale-reading hypotheses. Thin margin only in the most extreme tested cell.",
  C: "Protects the reserve but misses the deadline: reserve protection conflicts with restoration time.",
};

function RiskMatrix({ cells }: { cells: Cell[] }) {
  return (
    <div className="grid w-[74px] grid-cols-3 gap-1" role="img"
      aria-label={`${cells.filter((c) => c.violation).length} of ${cells.length} hypothetical conditions breach the reserve floor`}>
      {cells.map((c, i) => (
        <div key={i} title={`SoH ${c.soh}, drain ×${c.drain_multiplier}: lowest ${c.min_soc}% (${c.margin_to_floor >= 0 ? "+" : ""}${c.margin_to_floor} pts to floor)`}
          className={`flex h-[22px] items-center justify-center rounded-md border text-[11px] font-bold ${c.violation ? "border-rose-700 bg-rose-900 text-rose-300" : "border-emerald-700 bg-emerald-950 text-emerald-300"}`}>
          {c.violation ? "✗" : "✓"}
        </div>
      ))}
    </div>
  );
}

function TimeBar({ minutes, objective, late }: { minutes: number; objective: number; late: boolean }) {
  const max = Math.max(objective * 3, minutes);
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-slate-800" role="img" aria-label={`Recovery ${minutes} minutes against a ${objective}-minute objective`}>
        <div className={`h-full rounded-full ${late ? "bg-amber-600" : "bg-cyan-600"}`} style={{ width: `${Math.max(3, (minutes / max) * 100)}%` }} />
        <div className="absolute -top-1 h-4.5 w-0.5 bg-slate-100" style={{ left: `${(objective / max) * 100}%`, height: 18 }} title={`${objective}-min objective`} />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400"><span className="mono">{minutes} min</span><span>objective {objective} min</span></div>
    </div>
  );
}

/** Campus framing of the existing scenario. All numbers on this page come from the Shadow Twin API or are labelled scenario settings. */
export function CampusView({ go }: { go: Go }) {
  const [res, setRes] = useState<Shadow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setErr("");
    try {
      const out: Shadow[] = [];
      for (const p of ["A", "B", "C"]) {
        const r = await fetch("/api/shadow/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id: p }) });
        if (r.status === 401 || r.status === 503) throw new Error("Authentication required: sign in with the demo credentials and retry.");
        if (!r.ok) throw new Error(`The server returned HTTP ${r.status}.`);
        out.push(await r.json());
      }
      setRes(out);
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const f = res?.[0];
  const steps: [string, string, string][] = [
    ["shadow", "1 · Challenge the plan", "Test it against hidden battery states before anything runs."],
    ["shield", "2 · Independent safety gate", "Deterministic rules R1–R7. No operator, model or approval can override it."],
    ["user", "3 · Human approval", "Consequential actions wait for a person; the gate re-checks first."],
    ["record", "4 · Verify and prove", "Simulated execution, verification, and an exportable proof record."],
  ];

  return (
    <div className="space-y-6">
      <section aria-labelledby="hero" className="rise relative overflow-hidden rounded-2xl border border-slate-700/70 bg-white p-5 shadow-lift md:p-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-[radial-gradient(circle,rgb(91_82_232/0.16),transparent_65%)]" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[radial-gradient(circle,rgb(14_165_168/0.12),transparent_65%)]" />
        <div className="relative grid gap-6 lg:grid-cols-[1.25fr_1fr] lg:items-center">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-400">AEGIS — Counterfactual Safety Agent · Campus Energy Resilience profile</div>
            <h1 id="hero" className="mt-2 text-[2rem] font-semibold leading-[1.1] text-slate-100 md:text-[2.7rem]">Know the risk before you commit to recovery.</h1>
            <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-slate-300">
              When a campus water pump fails and the battery reading is stale, the fastest recovery plan can quietly breach the reserve your critical
              loads depend on. AEGIS tests each plan against hidden failure conditions, applies an independent safety gate, and requires human
              approval before anything runs.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <button className="btn-p" onClick={() => go("console")}>Run the incident <Icon name="arrow" /></button>
              <button className="btn-s" onClick={() => go("shadow")}><Icon name="shadow" /> Open Shadow twin</button>
              <button className="btn-s" onClick={() => go("data")}><Icon name="data" /> Real data</button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3" aria-label="Scenario settings">
            <Metric label="Reserve floor" value={f ? `${f.reserve_floor_pct}%` : <Skeleton h={28} w="60%" />} sub="battery charge for critical loads" kind="simulated" />
            <Metric label="Recovery objective" value={f ? `${f.recovery_objective_min} min` : <Skeleton h={28} w="60%" />} sub="simulated minutes" kind="simulated" />
            <Metric label="Starting charge" value={f ? `${f.initial_soc}%` : <Skeleton h={28} w="60%" />} sub="scenario setting" kind="simulated" />
            <Metric label="Battery reading age" value="47 min" sub="limit 10 min: flagged stale" tone="warn" kind="simulated" />
          </div>
        </div>
      </section>

      <section aria-label="How AEGIS decides" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map(([ic, t, d], i) => (
          <div key={t} className="rise rounded-xl border border-slate-700/70 bg-white p-4 shadow-card" style={{ animationDelay: `${i * 60}ms` }}>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-900 text-cyan-400"><Icon name={ic} size={18} /></div>
            <div className="mt-2.5 text-sm font-semibold text-slate-100">{t}</div>
            <div className="mt-0.5 text-[13px] leading-relaxed text-slate-300">{d}</div>
          </div>
        ))}
      </section>

      <section aria-labelledby="plans">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="plans" className="text-xl font-semibold text-slate-100">Reserve protection versus restoration deadline</h2>
            <p className="text-sm text-slate-400">Three candidate plans, each run on 9 hypothetical battery conditions by the Shadow Twin.</p>
          </div>
          <button className="btn-s" disabled={busy} onClick={load}>{busy ? "Loading…" : "Refresh"}</button>
        </div>
        {err && <Banner tone="warn" title="Could not load the comparison">{err} <button className="underline" onClick={load}>Retry</button></Banner>}
        {!res && !err && (
          <div className="grid gap-4 lg:grid-cols-3" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="panel space-y-3"><Skeleton h={22} w="60%" /><Skeleton h={10} /><Skeleton h={70} w="40%" /><Skeleton h={34} /></div>)}</div>
        )}
        {res && (
          <div className="grid gap-4 lg:grid-cols-3">
            {res.map((r, i) => {
              const g = GATE[r.plan.id]; const bad = r.summary.violating;
              return (
                <article key={r.plan.id} className="rise flex flex-col rounded-2xl border border-slate-700/70 bg-white p-5 shadow-card transition-shadow hover:shadow-lift" style={{ animationDelay: `${i * 70}ms` }}>
                  <header className="flex items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-lg font-semibold text-white">{r.plan.id}</div>
                    <div><h3 className="text-base font-semibold text-slate-100">{r.plan.name}</h3>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge tone={g.tone}>{g.tone === "ok" ? "✓" : "✗"} {g.text}</Badge>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">Gate verdict for the design scenario (seed 42), not computed on this page</div>
                    </div>
                  </header>
                  <div className="mt-4"><TimeBar minutes={r.plan.restore_min} objective={r.recovery_objective_min} late={r.summary.misses_deadline} /></div>
                  {r.summary.misses_deadline && <div className="mt-2 flex items-center gap-1.5 text-xs font-medium text-amber-300"><Icon name="clock" size={14} /> Misses the {r.recovery_objective_min}-minute objective</div>}
                  <div className="mt-4 flex items-center gap-4">
                    <RiskMatrix cells={r.cells} />
                    <div>
                      <div className={`mono text-2xl font-semibold ${bad ? "text-rose-300" : "text-emerald-300"}`}>{bad} <span className="text-sm font-medium text-slate-400">of {r.summary.cells}</span></div>
                      <div className="text-xs text-slate-400">hypothetical conditions breach the floor</div>
                      <div className="mt-0.5 text-xs text-slate-400">lowest charge <span className="mono font-semibold text-slate-200">{Math.min(...r.cells.map((c) => c.min_soc))}%</span></div>
                    </div>
                  </div>
                  <p className="mt-3 flex-1 text-[13px] leading-relaxed text-slate-300">{NOTE[r.plan.id]}</p>
                </article>
              );
            })}
          </div>
        )}
        {res && (
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1"><span className="inline-block h-3.5 w-3.5 rounded border border-emerald-700 bg-emerald-950 text-center text-[9px] font-bold leading-[13px] text-emerald-300">✓</span> floor held</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-3.5 w-3.5 rounded border border-rose-700 bg-rose-900 text-center text-[9px] font-bold leading-[13px] text-rose-300">✗</span> floor breached</span>
            <span>Hover a square for its condition. Squares are battery health × extra drain. These are hypothetical scenarios run without the runtime monitor, not telemetry and not a safety guarantee.</span>
          </div>
        )}
      </section>

      <section aria-labelledby="prov" className="grid gap-3 md:grid-cols-3">
        <h2 id="prov" className="sr-only">What is measured, simulated and assumed</h2>
        <div className="panel"><Provenance kind="measured" />
          <p className="mt-2 text-sm leading-relaxed text-slate-300">Real All-India grid demand from the National Power Portal (2026-10-23), in MW, on the{" "}
            <button className="font-medium text-cyan-400 underline" onClick={() => go("data")}>Real data</button> tab. It is context only: never campus telemetry, never battery input.</p></div>
        <div className="panel"><Provenance kind="simulated" />
          <p className="mt-2 text-sm leading-relaxed text-slate-300">The campus, its pumps, battery, grid tie and faults, and every charge level and recovery time on this page. Values are illustrative.</p></div>
        <div className="panel"><Provenance kind="assumed" />
          <p className="mt-2 text-sm leading-relaxed text-slate-300">Battery response curves, scenario weights, and the link from grid-demand shape to extra campus drain. No campus telemetry, savings or equipment specifications are claimed.</p></div>
      </section>
    </div>
  );
}

import { useState } from "react";
import { Badge } from "./panels";

type Cell = { soh: number; drain_multiplier: number; restored: boolean; restore_min: number | null; min_soc: number;
  margin_to_floor: number; violations: string[]; violation: boolean };
type Shadow = {
  label: string; plan: { id: string; name: string; restore_min: number }; reserve_floor_pct: number;
  recovery_objective_min: number; initial_soc: number; grid: { soh: number[]; drain_multipliers: number[] };
  cells: Cell[]; explanation: string;
  summary: { cells: number; violating: number; fragility: number; min_margin_pts: number; verdict: string; misses_deadline: boolean };
};

const PLANS: Record<string, string> = { A: "A · Fast restore", B: "B · Staged restore", C: "C · Wait for maintenance" };

export function ShadowView() {
  const [plan, setPlan] = useState("A");
  const [res, setRes] = useState<Shadow | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ kind: "auth" | "input" | "other"; text: string } | null>(null);

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/shadow/run", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: plan }) });
      const body = await r.json().catch(() => ({}));
      if (r.status === 401) setErr({ kind: "auth", text: "Authentication required: sign in with the demo credentials and retry." });
      else if (r.status === 503) setErr({ kind: "auth", text: "This server has no access configured (production fails closed)." });
      else if (r.status === 422) setErr({ kind: "input", text: typeof body.detail === "string" ? body.detail : "The request was rejected as invalid." });
      else if (!r.ok) setErr({ kind: "other", text: `Server error (HTTP ${r.status}). Try again.` });
      else setRes(body as Shadow);
    } catch {
      setErr({ kind: "other", text: "Could not reach the server." });
    } finally { setBusy(false); }
  };

  const cell = (soh: number, m: number) => res?.cells.find((c) => c.soh === soh && c.drain_multiplier === m);
  const s = res?.summary;
  const tone = !s ? "mute" : s.violating ? "bad" : s.misses_deadline ? "warn" : "ok";

  return (
    <div className="space-y-4">
      <div className="panel text-sm text-slate-300">
        <div className="h">Shadow twin · counterfactual recovery test</div>
        <p>Pick one recovery plan and run it on the simulator across a 3 × 3 grid of <b>hypothetical</b> states: battery health (the stale-reading
          hypotheses) × unmodelled extra drain. Nothing here is telemetry, and nothing is executed in a live incident.</p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-400">Plan<br />
            <select className="inp" value={plan} onChange={(e) => { setPlan(e.target.value); setRes(null); }}>
              {Object.entries(PLANS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <button className="btn-p" disabled={busy} onClick={run}>{busy ? "Running…" : "▶ Run shadow twin"}</button>
        </div>
      </div>

      <div className="rounded-md border border-amber-700 bg-amber-950/30 p-2 text-xs text-amber-200">
        <b>Limitation.</b> Results cover only these tested hypothetical scenarios, run <b>without the runtime monitor</b>. They are not a real-world
        safety guarantee, and "robust" means only "no violation in the cells tried".
      </div>

      {err && <div className={`panel !py-2 text-sm ${err.kind === "auth" ? "text-amber-300" : "text-rose-300"}`} role="alert">
        {err.kind === "auth" ? "🔒 " : err.kind === "input" ? "Invalid request: " : ""}{err.text}</div>}
      {busy && !res && <div className="panel text-sm text-slate-400">Running 9 simulator scenarios…</div>}
      {!res && !busy && !err && <div className="panel text-sm text-slate-500">No result yet. Choose a plan and run the shadow twin.</div>}

      {res && s && (
        <div className="panel space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h !mb-0">Plan {res.plan.id} · {res.plan.name}</div>
            <Badge tone={tone}>{s.verdict.toUpperCase()}</Badge>
            <Badge tone={s.violating ? "bad" : "ok"}>{s.violating} of {s.cells} cells breach the {res.reserve_floor_pct}% floor</Badge>
            <span className="text-xs text-slate-400">thinnest margin {s.min_margin_pts >= 0 ? "+" : ""}{s.min_margin_pts} pts · starts at {res.initial_soc}% charge</span>
          </div>
          <p className="text-sm text-slate-200">{res.explanation}</p>

          <div className={`rounded-md border p-2 text-sm ${s.misses_deadline ? "border-amber-700 bg-amber-950/30 text-amber-200" : "border-slate-800 text-slate-300"}`}>
            Recovery time: <b>{res.plan.restore_min} min</b> against the <b>{res.recovery_objective_min}-min</b> objective
            {s.misses_deadline ? " — misses the deadline, even though the reserve may hold. The safety gate rejects this plan under R7." : " — meets the deadline."}
          </div>

          <div role="group" aria-label="Risk matrix: battery health by extra drain">
            <div className="mb-1.5 flex items-end justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
              <span>Battery health (SoH) ↓</span><span>Extra drain beyond the model →</span>
            </div>
            <div className="grid grid-cols-[3.2rem_repeat(3,minmax(0,1fr))] gap-1.5 sm:gap-2">
              <div />
              {res.grid.drain_multipliers.map((m) => <div key={m} className="mono pb-0.5 text-center text-xs font-semibold text-slate-300">×{m.toFixed(2)}</div>)}
              {res.grid.soh.map((h) => (
                <div key={h} className="contents">
                  <div className="mono flex items-center text-xs font-semibold text-slate-300">{h.toFixed(2)}</div>
                  {res.grid.drain_multipliers.map((m) => {
                    const c = cell(h, m);
                    if (!c) return <div key={m} />;
                    return (
                      <div key={m} tabIndex={0} title={`SoH ${h}, drain ×${m}: lowest charge ${c.min_soc}%, ${c.margin_to_floor >= 0 ? "+" : ""}${c.margin_to_floor} pts to the ${res.reserve_floor_pct}% floor`}
                        className={`rounded-lg border p-2 sm:p-2.5 ${c.violation ? "border-rose-700 bg-rose-900 text-rose-200" : "border-emerald-700 bg-emerald-950 text-emerald-200"}`}>
                        <div className="flex items-center justify-between gap-1">
                          <span className="mono text-base font-semibold sm:text-lg">{c.min_soc}%</span>
                          <span className="text-xs font-bold" aria-label={c.violation ? "breaches the floor" : "holds the floor"}>{c.violation ? "✗ Breach" : "✓ Holds"}</span>
                        </div>
                        <div className="mt-0.5 text-[11px] leading-snug">{c.margin_to_floor >= 0 ? "+" : ""}{c.margin_to_floor} pts to floor</div>
                        <div className="text-[11px] leading-snug opacity-80">{c.violation ? `violates ${c.violations.join(", ")}` : "no violation"} · {c.restored ? `restored ${c.restore_min} min` : "not restored"}</div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-emerald-700 bg-emerald-950" /> ✓ holds the {res.reserve_floor_pct}% floor</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded border border-rose-700 bg-rose-900" /> ✗ breaches the floor</span>
              <span>Each square is a <b>hypothetical simulated condition</b>, not measured telemetry. Hover or focus a square for detail.</span>
            </div>
          </div>
          <div className="text-[11px] text-slate-500">{res.label}</div>
        </div>
      )}
    </div>
  );
}

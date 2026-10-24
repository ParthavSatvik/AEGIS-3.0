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

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400">
                <th className="py-1 pr-3">Battery health (SoH) ↓ / extra drain →</th>
                {res.grid.drain_multipliers.map((m) => <th key={m} className="pr-3">×{m.toFixed(2)}</th>)}</tr></thead>
              <tbody>
                {res.grid.soh.map((h) => (
                  <tr key={h} className="border-t border-slate-800 align-top">
                    <td className="mono py-2 pr-3">{h.toFixed(2)}</td>
                    {res.grid.drain_multipliers.map((m) => {
                      const c = cell(h, m);
                      if (!c) return <td key={m} />;
                      return (
                        <td key={m} className={`pr-3 ${c.violation ? "rounded bg-rose-950/50 text-rose-200" : ""}`}>
                          <div className="mono font-semibold">{c.min_soc}% {c.violation ? "✗" : "✓"}</div>
                          <div className="text-[11px]">{c.margin_to_floor >= 0 ? "+" : ""}{c.margin_to_floor} pts to floor</div>
                          <div className="text-[11px]">{c.violation ? `violates ${c.violations.join(", ")}` : "no violation"}</div>
                          <div className="text-[11px] text-slate-400">{c.restored ? `restored ${c.restore_min} min` : "not restored"}</div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-[11px] text-slate-500">{res.label}</div>
        </div>
      )}
    </div>
  );
}

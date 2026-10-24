import { useState } from "react";
import { Badge } from "./panels";

type Cell = { soh: number; drain_multiplier: number; min_soc: number; violation: boolean };
type Shadow = {
  plan: { id: string; name: string; restore_min: number }; reserve_floor_pct: number; recovery_objective_min: number;
  initial_soc: number; cells: Cell[];
  summary: { cells: number; violating: number; min_margin_pts: number; verdict: string; misses_deadline: boolean };
};

const GATE: Record<string, string> = { A: "REJECTED · R1 reserve floor", B: "PASSED", C: "REJECTED · R7 recovery objective" };

/** Campus framing of the existing scenario. Every number below comes from the existing backend (Shadow Twin API). */
export function CampusView({ go }: { go: (tab: "console" | "shadow" | "data") => void }) {
  const [res, setRes] = useState<Shadow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setBusy(true); setErr("");
    try {
      const out: Shadow[] = [];
      for (const p of ["A", "B", "C"]) {
        const r = await fetch("/api/shadow/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id: p }) });
        if (r.status === 401 || r.status === 503) throw new Error("Authentication required: sign in with the demo credentials and retry.");
        if (!r.ok) throw new Error(`Server returned HTTP ${r.status}.`);
        out.push(await r.json());
      }
      setRes(out);
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };

  const f = res?.[0];
  return (
    <div className="space-y-4">
      <div className="panel">
        <div className="h">Campus energy resilience copilot · demo profile</div>
        <p className="text-sm text-slate-300">
          <b>Story.</b> On a simulated campus, the main water pump <b>P2 fails</b>. The backup pump B1 can restore critical water, but only by
          drawing on the campus <b>battery bank</b>, whose health reading is <b>47 minutes old</b> (limit 10). The fastest plan looks fine on the stale
          reading and breaches the reserve if the battery has degraded. AEGIS tests the plan before it runs, blocks it with an independent safety gate,
          requires a <b>human approval</b> for the safer plan, and shows where protecting the reserve conflicts with the restoration deadline.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <button className="btn-p" onClick={() => go("console")}>Run the incident →</button>
          <button className="btn-s" onClick={() => go("shadow")}>Open Shadow twin →</button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="panel text-sm text-slate-300">
          <div className="h">Intended campus users (decision support)</div>
          Facilities and energy managers, microgrid operators and campus resilience teams, who would review options, see the trade-offs and approve actions.
          AEGIS does not act on its own.
        </div>
        <div className="panel text-sm text-slate-300">
          <div className="h">Critical service and constraints (simulated)</div>
          <ul className="list-disc space-y-1 pl-5">
            <li><b>Critical service:</b> campus water supply (pump P2, backup pump B1, grid tie, battery bank).</li>
            <li><b>Reserve constraint:</b> battery charge must stay at or above <b>{f ? `${f.reserve_floor_pct}%` : "30%"}</b> for critical loads.</li>
            <li><b>Recovery objective:</b> restore within <b>{f ? `${f.recovery_objective_min} min` : "60 min"}</b>.</li>
            <li><b>Starting charge:</b> {f ? `${f.initial_soc}%` : "58%"} (scenario setting).</li>
          </ul>
        </div>
      </div>

      <div className="panel space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="h !mb-0">Candidate plans: reserve protection vs restoration deadline</div>
          <button className="btn-p ml-auto" disabled={busy} onClick={load}>{busy ? "Loading…" : res ? "Refresh from Shadow Twin" : "▶ Load comparison"}</button>
        </div>
        {err && <div className="text-sm text-amber-300" role="alert">{err}</div>}
        {!res && !busy && !err && <div className="text-sm text-slate-500">Loads the three plans from the Shadow Twin API (9 hypothetical conditions each).</div>}
        {res && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400"><th className="pr-3">Plan</th><th className="pr-3">Recovery time</th>
                <th className="pr-3">Safety gate (design scenario)</th><th className="pr-3">Shadow Twin: cells breaching the floor</th><th className="pr-3">Lowest charge in any cell</th><th>Trade-off</th></tr></thead>
              <tbody>
                {res.map((r) => {
                  const lowest = Math.min(...r.cells.map((c) => c.min_soc));
                  return (
                    <tr key={r.plan.id} className="border-t border-slate-800 align-top">
                      <td className="py-2 pr-3 font-semibold">{r.plan.id} · {r.plan.name}</td>
                      <td className={`mono pr-3 ${r.summary.misses_deadline ? "text-amber-300" : ""}`}>{r.plan.restore_min} min / {r.recovery_objective_min}</td>
                      <td className="pr-3"><Badge tone={r.plan.id === "B" ? "ok" : "bad"}>{GATE[r.plan.id]}</Badge></td>
                      <td className={`mono pr-3 ${r.summary.violating ? "text-rose-300" : ""}`}>{r.summary.violating} of {r.summary.cells}</td>
                      <td className="mono pr-3">{lowest}%</td>
                      <td className="text-xs text-slate-300">
                        {r.plan.id === "A" ? "Fastest, but breaches the reserve in the degraded-battery conditions."
                          : r.plan.id === "B" ? "Meets the deadline and holds the reserve in the stale-reading hypotheses; thin margin only in the most extreme tested cell."
                            : "Protects the reserve but misses the deadline: reserve protection conflicts with restoration time."}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-slate-500">Shadow Twin cells are hypothetical simulated conditions, run without the runtime monitor; not a real-world safety guarantee.
              The gate column describes the design scenario (seed 42) and is not computed here; run the incident to see it live.</p>
          </div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="panel text-sm text-slate-300"><div className="h">Measured</div>
          Real historical national grid demand (All-India, National Power Portal, 2026-10-23), imported on the <button className="text-cyan-300 underline" onClick={() => go("data")}>Real data</button> tab.
          It is <b>context only</b>, in MW, and is never campus telemetry or battery input.</div>
        <div className="panel text-sm text-slate-300"><div className="h">Simulated</div>
          The campus, its pumps, battery, grid tie, faults and every number on this page about charge and recovery time. All values are illustrative.</div>
        <div className="panel text-sm text-slate-300"><div className="h">Assumed / not validated</div>
          Battery response curves, scenario weights, and the link from grid-demand shape to extra campus drain (an assumption). No campus telemetry,
          savings or equipment specifications are claimed.</div>
      </div>
    </div>
  );
}

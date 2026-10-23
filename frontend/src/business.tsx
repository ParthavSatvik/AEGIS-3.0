import { useState } from "react";
import type { Cycle, EpState } from "./api";
import { Badge } from "./panels";

type Tone = "ok" | "bad" | "warn" | "info" | "mute";

/** Data ingestion -> intelligent decision -> responsible execution -> outcome reporting, driven by the record. */
export function Pipeline({ st, cycle }: { st: EpState; cycle?: Cycle }) {
  const a = st.assessment.readings;
  const flagged = Object.values(a).filter((r) => r.status !== "fresh").length;
  const rec = st.record;
  const rep = rec.outcome_report;
  const lastApproval = rec.approvals.filter((x) => x.decision !== "auto").at(-1);
  const steps: { title: string; body: string; tone: Tone }[] = [
    { title: "1 · Data ingestion", tone: flagged ? "warn" : "ok",
      body: `${Object.keys(a).length} simulated telemetry streams ingested · ${flagged} flagged stale/missing/invalid` },
    { title: "2 · Intelligent decision", tone: cycle?.outcomes ? "info" : "mute",
      body: cycle?.outcomes
        ? `${cycle.outcomes.length} plans × ${cycle.hidden_states_initial?.length ?? 0} hidden states · ${cycle.counterexamples_initial?.length ?? 0} counterexample(s) · ${(cycle.diagnostics ?? []).filter((d) => d.ran).length} diagnostic(s) run`
        : "Awaiting decision cycle" },
    { title: "3 · Responsible execution", tone: rec.pending_approval ? "warn" : lastApproval ? (lastApproval.result === "EXECUTED" ? "ok" : "bad") : cycle?.status === "abstained" ? "bad" : "mute",
      body: rec.pending_approval ? `Human approval required for plan ${rec.pending_approval.plan_id}`
        : lastApproval ? `${lastApproval.operator} ${lastApproval.decision} ${lastApproval.plan_id} → ${lastApproval.result ?? ""}`
        : cycle?.status === "abstained" ? "Abstained: nothing executed" : "Human approval + independent safety gate" },
    { title: "4 · Outcome reporting", tone: rep?.incidents.some((i) => i.outcome === "restored") ? "ok" : rep?.abstentions ? "bad" : "mute",
      body: rep ? `${rep.incidents.filter((i) => i.outcome === "restored").length}/${rep.incidents.length} incident(s) restored & verified · ${rep.unsafe_plan_verdicts_blocked} unsafe verdicts blocked`
        : "Verification, metrics and proof record" },
  ];
  const border: Record<Tone, string> = { ok: "border-emerald-700", bad: "border-rose-700", warn: "border-amber-600", info: "border-cyan-700", mute: "border-slate-800" };
  return (
    <div className="grid gap-2 md:grid-cols-4">
      {steps.map((s) => (
        <div key={s.title} className={`panel !p-3 border-l-4 ${border[s.tone]}`}>
          <div className="text-xs font-semibold text-slate-200">{s.title}</div>
          <div className="mt-1 text-xs text-slate-400">{s.body}</div>
        </div>
      ))}
    </div>
  );
}

export function Telemetry({ st }: { st: EpState }) {
  const r = st.observation.readings, a = st.assessment.readings;
  const tone = (s: string): Tone => (s === "fresh" ? "ok" : s === "stale" ? "warn" : "bad");
  return (
    <div className="panel overflow-x-auto">
      <div className="h">Data ingestion · simulated utility telemetry</div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-400"><th className="pr-3">Stream</th><th className="pr-3">Value</th><th className="pr-3">Age</th><th>Status</th></tr></thead>
        <tbody>
          {Object.values(r).map((x) => (
            <tr key={x.name} className="border-t border-slate-800">
              <td className="mono py-1 pr-3 text-slate-300">{x.name}</td>
              <td className="mono pr-3">{x.value === null ? "—" : String(x.value)}</td>
              <td className="mono pr-3">{x.age_min == null ? "—" : `${x.age_min} min`}</td>
              <td><Badge tone={tone(a[x.name]?.status ?? "missing")}>{(a[x.name]?.status ?? "missing").toUpperCase()}</Badge>
                {a[x.name]?.reason && <span className="ml-2 text-xs text-slate-500">{a[x.name].reason}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Approval({ st, busy, onDecide }: { st: EpState; busy: boolean; onDecide: (approve: boolean, operator: string) => void }) {
  const [op, setOp] = useState("duty-operator");
  const p = st.record.pending_approval;
  if (!p) return null;
  return (
    <div className="panel border-amber-600 bg-amber-950/20">
      <div className="h !text-amber-300">Human approval required · consequential recovery action</div>
      <div className="text-sm text-slate-200">
        <b>Plan {p.plan_id} · {p.plan_name}</b> — {p.description} <span className="text-xs text-slate-400">(proposed by {p.source})</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <Badge tone="warn">actions: {p.consequential_actions.join(", ")}</Badge>
        <Badge tone="ok">gate {p.gate_status}</Badge>
        <Badge tone="info">worst-case reserve {p.worst_case_reserve_pct}% over {p.states_checked} states</Badge>
        <Badge tone="info">restore at {p.elapsed_min + p.restore_min} / {st.constraints.recovery_objective_min} min</Badge>
        <span className="mono text-slate-500">evidence {p.fingerprint}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-400">Operator<br />
          <input className="inp" value={op} maxLength={60} onChange={(e) => setOp(e.target.value)} />
        </label>
        <button className="btn-p" disabled={busy || !op.trim()} onClick={() => onDecide(true, op.trim())}>Approve & execute</button>
        <button className="btn-d" disabled={busy || !op.trim()} onClick={() => onDecide(false, op.trim())}>Reject (take manual control)</button>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">
        Approval is bound to this evidence. On approval the backend re-runs the safety gate on fresh telemetry: if the plan is
        now unsafe it is blocked and AEGIS replans; if the evidence changed, re-approval is required. Approval never overrides safety.
      </p>
    </div>
  );
}

export function OutcomeReportPanel({ st }: { st: EpState }) {
  const r = st.record.outcome_report;
  if (!r || !r.incidents.length) return null;
  const Stat = ({ k, v, tone }: { k: string; v: React.ReactNode; tone?: string }) => (
    <div className="rounded-md border border-slate-800 p-2"><div className="text-[11px] uppercase text-slate-500">{k}</div><div className={`mono text-base ${tone ?? "text-slate-100"}`}>{v}</div></div>
  );
  return (
    <div className="panel">
      <div className="h">Outcome reporting · business metrics (simulated; from observations only)</div>
      <table className="mb-3 w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-400"><th>Incident</th><th>Outcome</th><th>Simulated restoration time (sim-min)</th><th>Executed</th><th>Diagnostics (cost / delay)</th></tr></thead>
        <tbody>
          {r.incidents.map((i, k) => (
            <tr key={k} className="border-t border-slate-800">
              <td className="py-1">{i.incident.replace("_", " ")} @ t={i.start_t_min}m</td>
              <td><Badge tone={i.outcome === "restored" ? "ok" : i.outcome === "in progress" ? "warn" : "bad"}>{i.outcome.toUpperCase()}</Badge></td>
              <td className="mono">{i.simulated_restoration_min == null ? "—" : `${i.simulated_restoration_min} / ${r.recovery_objective_min} sim-min`}</td>
              <td className="mono">{i.executed.join(" → ") || "—"}</td>
              <td className="mono">{i.diagnostics_run} ({i.diagnostic_cost} / {i.diagnostic_delay_min} min)</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat k="Min reserve observed" v={r.min_reserve_observed_pct == null ? "—" : `${r.min_reserve_observed_pct}% (floor ${r.reserve_floor_pct}%)`}
          tone={r.min_reserve_observed_pct != null && r.min_reserve_observed_pct < r.reserve_floor_pct ? "text-rose-300" : "text-emerald-300"} />
        <Stat k="Unsafe plan verdicts blocked" v={r.unsafe_plan_verdicts_blocked} />
        <Stat k="Counterexamples found pre-action" v={r.counterexamples_found} />
        <Stat k="Human approvals / rejections" v={`${r.human_approvals} / ${r.human_rejections}`} />
        <Stat k="Approvals blocked by gate" v={r.approvals_blocked_by_gate} />
        <Stat k="Forced requests blocked" v={r.forced_requests_blocked} />
        <Stat k="Replans" v={r.replans} />
        <Stat k="Abstentions (handed over)" v={r.abstentions} />
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Human approval wait: <span className="mono">{r.human_approval_wait_wall_s} s</span> real wall-clock time. The simulation clock is
        paused while a proposal waits, so this is <b>not</b> included in simulated restoration time. All times are simulated, not field measurements.
      </p>
    </div>
  );
}

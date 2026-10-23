import { useState } from "react";
import type { Cycle, EpState, EventT, Exec, Verification, Verdict } from "./api";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");
const f1 = (n: number) => n.toFixed(1);

export function Badge({ tone, children }: { tone: "ok" | "bad" | "warn" | "info" | "mute"; children: React.ReactNode }) {
  const t = {
    ok: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
    bad: "bg-rose-900/50 text-rose-300 border-rose-700",
    warn: "bg-amber-900/50 text-amber-300 border-amber-700",
    info: "bg-cyan-900/40 text-cyan-300 border-cyan-800",
    mute: "bg-slate-800 text-slate-400 border-slate-700",
  }[tone];
  return <span className={cx("inline-block rounded border px-1.5 py-0.5 text-[11px] font-semibold", t)}>{children}</span>;
}

function Card({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className={cx("panel !p-3", tone)}>
      <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-100">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export function StatusCards({ st, cycle }: { st: EpState; cycle?: Cycle }) {
  const o = st.observation, c = st.constraints, r = o.readings, a = st.assessment.readings;
  const soh = r.battery_soh, sohS = a.battery_soh?.status ?? "missing";
  const soc = Number(r.battery_soc.value);
  const ab = st.record.abstentions.length > 0 && cycle?.status === "abstained";
  const verdict = ab ? <Badge tone="bad">ABSTAIN</Badge>
    : cycle?.selected ? <Badge tone="ok">PASS · {cycle.selected}</Badge>
    : cycle?.gate ? <Badge tone="bad">BLOCK</Badge> : <span className="text-slate-500">—</span>;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Card label="Incident" value={o.incident ? <span className="text-rose-300">{o.incident.replace("_", " ")}</span>
        : <span className="text-emerald-300">{st.record.abstentions.length && !o.service_restored ? "handed over" : "service up"}</span>}
        sub={`t = ${o.t_min} min · P2 ${r.pump_P2.value} · B1 ${r.pump_B1.value} · grid ${r.grid_tie.value}`} />
      <Card label="Battery SoH reading"
        value={<>{soh.value === null ? "—" : typeof soh.value === "number" ? `${(soh.value * 100).toFixed(0)}%` : String(soh.value)}{" "}
          <Badge tone={sohS === "fresh" ? "ok" : "warn"}>{sohS.toUpperCase()}</Badge></>}
        sub={soh.age_min == null ? "no timestamp" : `age ${f1(soh.age_min)} min · limit ${c.max_reading_age_min} min`} />
      <Card label="Battery SoC / reserve floor" value={<span className={soc < c.reserve_floor_pct ? "text-rose-300" : ""}>{f1(soc)}%</span>}
        sub={`floor ${c.reserve_floor_pct}% (hard constraint R1)`} />
      <Card label="Recovery clock (simulated)" value={o.incident ? `${o.incident_elapsed_min} / ${c.recovery_objective_min} sim-min` : "—"}
        sub="objective R7 (feasibility)" />
      <Card label="Replans used" value={`${st.replans_used} / ${c.replan_budget}`} sub={`B1 rated duty ${r.b1_rated_duty.value}`} />
      <Card label="Safety gate" value={verdict} sub={cycle ? `cycle ${cycle.cycle} · ${cycle.trigger}` : "no decision yet"} />
    </div>
  );
}

export function PlanTable({ cycle }: { cycle: Cycle }) {
  const [before, setBefore] = useState(true);
  const ranDiag = (cycle.diagnostics ?? []).some((d) => d.ran);
  const showInit = before && ranDiag;
  const rows = (showInit ? cycle.outcomes_initial : cycle.outcomes) ?? [];
  const states = (showInit ? cycle.hidden_states_initial : cycle.hidden_states) ?? [];
  const pre = cycle.counterexamples_initial ?? [];
  const init = cycle.hidden_states_initial ?? [];
  return (
    <div className="panel overflow-x-auto">
      <div className="flex flex-wrap items-center gap-2">
        <div className="h">Candidate plans × hidden states (planning model) — reserve after plan</div>
        {ranDiag && (
          <div className="mb-3 ml-auto flex gap-1">
            <button className={showInit ? "btn-p" : "btn-s"} onClick={() => setBefore(true)}>Before diagnostics</button>
            <button className={!showInit ? "btn-p" : "btn-s"} onClick={() => setBefore(false)}>After diagnostics</button>
          </div>
        )}
      </div>
      {init.length > 0 && (
        <div className="mb-3 text-xs text-slate-400">
          Challenge set before diagnostics:{" "}
          {init.map((s) => <span key={s.id} className="mono mr-2">{s.id}=SoH {s.soh.toFixed(2)} (w {s.weight})</span>)}
          {pre.length > 0 && <div className="mt-1 text-rose-300">
            {pre.map((x) => <div key={x.plan + x.state}>⚠ Counterexample: plan {x.plan} under {x.state} (SoH {x.soh.toFixed(2)}) → reserve {f1(x.reserve)}% &lt; {x.floor}% (margin {x.margin})</div>)}
          </div>}
        </div>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th className="py-1 pr-3">Plan</th><th className="pr-3">Restore</th>
            {states.map((s) => <th key={s.id} className="pr-3 mono" title={s.label}>{s.id}<div className="font-normal">SoH {s.soh.toFixed(2)} · w {s.weight}</div></th>)}
            <th className="pr-3">F<sub>unsafe</sub></th><th className="pr-3">Deadline</th><th>Gate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const g = showInit ? undefined : cycle.gate?.[r.plan_id];
            const sel = !showInit && cycle.selected === r.plan_id;
            return (
              <tr key={r.plan_id} className={cx("border-t border-slate-800 align-top", sel && "bg-emerald-950/40")}>
                <td className="py-2 pr-3">
                  <div className="font-semibold text-slate-100">{r.plan_id} · {r.name} {sel && <Badge tone="ok">SELECTED</Badge>}</div>
                  <div className="text-xs text-slate-500">{r.assumptions.join(" · ")}</div>
                </td>
                <td className="pr-3 mono">{r.restore_min}m</td>
                {r.outcomes.map((o) => (
                  <td key={o.state} className={cx("pr-3 mono", o.unsafe ? "text-rose-400 font-bold" : "text-emerald-300")}>
                    {f1(o.reserve)}%{o.unsafe && " ✗"}
                  </td>
                ))}
                <td className={cx("pr-3 mono", r.f_unsafe > 0 ? "text-rose-300" : "text-slate-300")}>{r.f_unsafe.toFixed(2)}</td>
                <td className="pr-3">{r.deadline_ok ? <Badge tone="ok">OK</Badge> : <Badge tone="bad">MISS</Badge>}</td>
                <td>{g && <Badge tone={g.passed ? "ok" : "bad"}>{g.status}</Badge>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-slate-500">
        F<sub>unsafe</sub>(a) = Σ w<sub>z</sub>·I[unsafe(a,z)] / Σ w<sub>z</sub>. Scenario weights are pre-set, not calibrated probabilities.
      </p>
    </div>
  );
}

export function Diagnostics({ cycle }: { cycle: Cycle }) {
  const ds = cycle.diagnostics ?? [];
  if (!ds.length) return null;
  return (
    <div className="panel">
      <div className="h">Decision-aware diagnostics · V(d) = E<sub>r</sub>[max U(a|r)] − max U(a) − c(d) − λt(d)</div>
      {ds.map((d, i) => (
        <div key={i} className="mb-3 last:mb-0">
          <div className="mb-1 text-xs text-slate-500">Round {i + 1}</div>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-400"><th>Diagnostic</th><th>E[U|r]</th><th>U now</th><th>c(d)</th><th>λt(d)</th><th>V(d)</th><th>Decision</th></tr></thead>
            <tbody>
              {d.values.map((v) => {
                const ran = d.ran?.diagnostic_id === v.diagnostic_id;
                return (
                  <tr key={v.diagnostic_id} className="border-t border-slate-800">
                    <td className="py-1.5" title={v.branches.map((b) => `${b.if_result}→${b.best_plan ?? "abstain"} (${b.utility})`).join(", ")}>
                      {v.name}{!v.permitted && <div className="text-[11px] text-slate-500">{v.blocked_reason}</div>}
                    </td>
                    <td className="mono">{v.expected_u_after.toFixed(1)}</td><td className="mono">{v.u_now.toFixed(1)}</td>
                    <td className="mono">{v.cost}</td><td className="mono">{v.delay_penalty}</td>
                    <td className={cx("mono font-bold", v.value > 0 ? "text-emerald-300" : "text-slate-400")}>{v.value >= 0 ? "+" : ""}{v.value.toFixed(2)}</td>
                    <td>{ran ? <Badge tone="info">RUN</Badge> : <Badge tone="mute">SKIP</Badge>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {d.ran && (
            <div className={cx("mt-2 rounded-md border p-2 text-sm", d.ran.conclusive ? "border-cyan-800 bg-cyan-950/30" : "border-amber-800 bg-amber-950/30")}>
              {d.ran.conclusive
                ? <>Result: measured SoH <b className="mono">{d.ran.measured?.toFixed(3)}</b> ± {d.ran.accuracy} → ruled out <b>{d.ran.ruled_out.join(", ") || "none"}</b>.</>
                : <>Result: <b>INCONCLUSIVE</b> — no hidden state removed (inconclusive ≠ safe).</>}
              {" "}Decision {d.ran.decision_before ?? "abstain"} → {d.ran.decision_after ?? "abstain"}{" "}
              <Badge tone={d.ran.decision_changed ? "info" : "mute"}>{d.ran.decision_changed ? "CHANGED DECISION" : "DECISION UNCHANGED"}</Badge>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7"];

export function Gate({ cycle }: { cycle: Cycle }) {
  const g = cycle.gate;
  if (!g) return null;
  const any = Object.values(g)[0] as Verdict | undefined;
  const title = (r: string) => any?.rules.find((x) => x.rule === r)?.title ?? r;
  return (
    <div className="panel overflow-x-auto">
      <div className="h">Independent safety gate (deterministic, fail-closed) — verdicts with rule IDs</div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-400"><th className="pr-2">Plan</th>{RULES.map((r) => <th key={r} title={title(r)} className="pr-2">{r}<div className="font-normal">{title(r)}</div></th>)}<th>Verdict</th></tr></thead>
        <tbody>
          {Object.values(g).map((v) => (
            <tr key={v.plan_id} className="border-t border-slate-800">
              <td className="py-1.5 pr-2 font-semibold">{v.plan_id}</td>
              {RULES.map((r) => {
                const x = v.rules.find((y) => y.rule === r);
                return <td key={r} className="pr-2" title={x?.detail}>{x ? (x.passed ? <span className="text-emerald-400">✓</span> : <span className="font-bold text-rose-400">✗</span>) : "—"}</td>;
              })}
              <td><Badge tone={v.passed ? "ok" : "bad"}>{v.status}</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 space-y-0.5 text-xs text-slate-400">
        {Object.values(g).flatMap((v) => v.rules.filter((r) => !r.passed).map((r) => <div key={v.plan_id + r.rule}><b className="text-rose-300">{v.plan_id} {r.rule}</b>: {r.detail}</div>))}
      </div>
      {cycle.abstention && (
        <div className="mt-3 rounded-md border border-rose-700 bg-rose-950/40 p-3 text-sm text-rose-200">
          <b>ABSTAINED</b> — {cycle.abstention.reason}. Nothing executed; control handed to the operator.
        </div>
      )}
    </div>
  );
}

function SocChart({ ex, floor }: { ex: Exec; floor: number }) {
  const pts = ex.soc_trace;
  if (pts.length < 2) return null;
  const W = 520, H = 140, P = 28;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0] || t0 + 1;
  const lo = Math.min(floor - 5, ...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1])) + 3;
  const x = (t: number) => P + ((t - t0) / Math.max(1, t1 - t0)) * (W - 2 * P);
  const y = (v: number) => H - P + 8 - ((v - lo) / (hi - lo)) * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Battery SoC trace">
      <line x1={P} x2={W - P} y1={y(floor)} y2={y(floor)} stroke="#f43f5e" strokeDasharray="4 3" />
      <text x={W - P} y={y(floor) - 4} fill="#fb7185" fontSize="10" textAnchor="end">reserve floor {floor}%</text>
      <polyline fill="none" stroke="#22d3ee" strokeWidth="2" points={pts.map((p) => `${x(p[0])},${y(p[1])}`).join(" ")} />
      <text x={P} y={H - 4} fill="#94a3b8" fontSize="10">t={t0}m</text>
      <text x={W - P} y={H - 4} fill="#94a3b8" fontSize="10" textAnchor="end">t={t1}m · SoC {pts[pts.length - 1][1]}%</text>
      <text x={P} y={y(pts[0][1]) - 4} fill="#94a3b8" fontSize="10">{pts[0][1]}%</text>
    </svg>
  );
}

export function Execution({ cycle, floor }: { cycle: Cycle; floor: number }) {
  const ex = cycle.executed, v: Verification | undefined = cycle.verification;
  if (!ex) return null;
  return (
    <div className="panel">
      <div className="h">Simulated execution & verification — plan {ex.plan_id}</div>
      <SocChart ex={ex} floor={floor} />
      {v && (
        <div className="mt-2 flex flex-wrap gap-2">
          {Object.entries(v.predicates).map(([k, ok]) => <Badge key={k} tone={ok ? "ok" : "bad"}>{ok ? "✓" : "✗"} {k.replace(/_/g, " ")}</Badge>)}
          <span className="text-xs text-slate-400">observed drain {v.observed_drain} pts · predicted [{v.predicted_drain_range.join(", ")}] · restored at {v.restored_elapsed_min ?? "—"} min</span>
        </div>
      )}
      <div className="mt-2 text-xs text-slate-400">{ex.events.join(" · ")}</div>
    </div>
  );
}

const TONE: Record<string, string> = { ok: "border-emerald-600", block: "border-rose-600", warn: "border-amber-500", info: "border-slate-600" };

export function Timeline({ events }: { events: EventT[] }) {
  return (
    <div className="panel max-h-[720px] overflow-y-auto">
      <div className="h">Live agent decision timeline</div>
      {!events.length && <div className="text-sm text-slate-500">Run a decision cycle to populate the timeline.</div>}
      <ol className="space-y-1.5">
        {events.map((e, i) => (
          <li key={i} className={cx("border-l-2 pl-2 text-xs", TONE[e.level] ?? TONE.info)}>
            <span className="mono text-slate-500">t={e.t_min}m</span> <span className="font-semibold uppercase text-slate-400">{e.stage}</span>
            <div className="text-slate-200">{e.message}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}

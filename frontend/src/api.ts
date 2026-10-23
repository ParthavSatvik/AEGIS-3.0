export type Rule = { rule: string; title: string; category: string; passed: boolean; detail: string };
export type Verdict = { plan_id: string; passed: boolean; status: string; rules: Rule[]; failed_closed: boolean };
export type State = { id: string; label: string; soh: number; weight: number; source: string };
export type Outcome = { state: string; soh: number; weight: number; reserve: number; unsafe: boolean };
export type Row = {
  plan_id: string; name: string; restore_min: number; utility: number; outcomes: Outcome[]; f_unsafe: number;
  deadline_ok: boolean; equipment_issues: string[]; assumptions: string[]; preview_eligible: boolean;
};
export type Cex = { plan: string; state: string; soh: number; rule: string; reserve: number; floor: number; margin: number };
export type Branch = { if_result: string; measured: number | null; weight: number; best_plan: string | null; utility: number };
export type DValue = {
  diagnostic_id: string; name: string; u_now: number; plan_now: string | null; expected_u_after: number; cost: number;
  delay_min: number; delay_penalty: number; value: number; permitted: boolean; blocked_reason: string; branches: Branch[];
};
export type DRan = {
  diagnostic_id: string; conclusive: boolean; measured: number | null; accuracy: number; ruled_out: string[];
  decision_before: string | null; decision_after: string | null; decision_changed: boolean; t_min: number;
};
export type Plan = { id: string; name: string; description: string; restore_min: number; actions: { type: string }[] };
export type Verification = {
  predicates: Record<string, boolean>; verified: boolean; observed_drain: number; predicted_drain_range: [number, number];
  min_reserve_observed: number; restored_elapsed_min: number | null;
};
export type Exec = { plan_id: string; t_start: number; t_end: number; soc_trace: [number, number][]; service_restored: boolean; events: string[] };
export type Cycle = {
  cycle: number; trigger: string; t_min: number; status?: string;
  stale_inputs?: { field: string; status: string; value: unknown; age_min: number | null; limit_min: number; reason: string }[];
  candidates?: Plan[]; hidden_states?: State[]; hidden_states_initial?: State[]; outcomes?: Row[]; outcomes_initial?: Row[];
  counterexamples?: Cex[]; counterexamples_initial?: Cex[];
  diagnostics?: { values: DValue[]; ran: DRan | null }[]; gate?: Record<string, Verdict>; selected?: string;
  executed?: Exec; verification?: Verification; abstention?: { reason: string; binding: Record<string, string> };
};
export type EventT = { t_min: number; stage: string; level: string; message: string };
export type ProofRecord = {
  decision_id: string; scenario_id: string; seed: number; arm: string; notice: string; cycles: Cycle[];
  events: EventT[]; replans: { trigger: string; replan_no: number }[]; abstentions: { reason: string }[];
  overrides: { plan_id: string; source: string; result?: string }[];
  explanation: { text: string; source: string; llm_error?: string } | null;
  pending_approval: Proposal | null;
  approvals: { t_min: number; plan_id: string; operator: string; decision: string; result?: string; gate_recheck?: string }[];
  outcome_report: OutcomeReport | null;
};
export type Proposal = {
  plan_id: string; plan_name: string; description: string; source: string; consequential_actions: string[];
  restore_min: number; elapsed_min: number; gate_status: string; worst_case_reserve_pct: number; states_checked: number;
  fingerprint: string; actions: Record<string, unknown>[];
};
export type OutcomeReport = {
  incidents: { incident: string; start_t_min: number; outcome: string; simulated_restoration_min: number | null;
    executed: string[]; diagnostics_run: number; diagnostic_cost: number; diagnostic_delay_min: number }[];
  recovery_objective_min: number; min_reserve_observed_pct: number | null; reserve_floor_pct: number;
  unsafe_plan_verdicts_blocked: number; counterexamples_found: number; human_approvals: number; human_rejections: number;
  approvals_blocked_by_gate: number; human_approval_wait_wall_s: number; forced_requests_blocked: number; replans: number; abstentions: number;
};
export type Reading = { name: string; value: number | string | null; age_min: number | null };
export type EpState = {
  episode_id: string; seed: number; closed: boolean; scenario: { id: string; title: string; description: string };
  observation: { t_min: number; incident: string | null; incident_elapsed_min: number; service_restored: boolean;
    active_plan: string | null; readings: Record<string, Reading> };
  assessment: { readings: Record<string, { status: string; reason: string; limit_min: number }> };
  constraints: { reserve_floor_pct: number; recovery_objective_min: number; max_reading_age_min: number; replan_budget: number };
  replans_used: number; record: ProofRecord;
};
export type Scenario = { id: string; title: string; description: string; demo: boolean; second_fault: string | null };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json() as Promise<T>;
}

export const api = {
  scenarios: () => call<{ scenarios: Scenario[]; faults: string[] }>("/api/scenarios"),
  start: (id: string, seed: number) => call<EpState>(`/api/scenarios/${id}/start?seed=${seed}`, { method: "POST" }),
  decide: (eid: string) => call<EpState>(`/api/episodes/${eid}/decide`, { method: "POST" }),
  fault: (eid: string, kind: string) =>
    call<EpState>(`/api/episodes/${eid}/faults`, { method: "POST", body: JSON.stringify({ kind }) }),
  override: (eid: string, plan_id: string, source: string) =>
    call<EpState & { request: { result: string; detail?: string; verdict?: Verdict } }>(`/api/episodes/${eid}/execute`, {
      method: "POST", body: JSON.stringify({ plan_id, source }) }),
  approve: (eid: string, approve: boolean, operator: string) =>
    call<EpState & { approval: { result: string; gate_recheck?: string } }>(`/api/episodes/${eid}/approve`, {
      method: "POST", body: JSON.stringify({ approve, operator }) }),
  explain: (eid: string) => call<ProofRecord["explanation"]>(`/api/episodes/${eid}/explain`, { method: "POST" }),
  record: (eid: string) => call<ProofRecord>(`/api/episodes/${eid}/record`),
  close: (eid: string) => call<Record<string, unknown>>(`/api/episodes/${eid}/close`, { method: "POST" }),
  bench: (seeds: number) => call<Bench>("/api/benchmarks/run", { method: "POST", body: JSON.stringify({ seeds }) }),
};

export type Agg = Record<string, number>;
export type Bench = {
  config: { seeds: number; families: string[]; arms: string[]; arm_labels: Record<string, string> };
  notice: string; summary: Record<string, Agg>; by_family: Record<string, Record<string, Agg>>;
  rows: Record<string, string | number>[]; digest: string; runtime_s: number;
  hypotheses?: { id: string; statement: string; result: string; evidence: string }[];
  reproducibility?: { reproducible: boolean };
};

export function download(name: string, text: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

import { useState } from "react";
import { Badge } from "./panels";

type Quality = Record<string, string | number>;
type Dataset = {
  id: string; name: string; source: string; filename: string; sha256: string; unit_in: string; unit: string;
  kind: string; quality: Quality; trend: { t: string; mw: number }[];
};
type Preview = { format: string; columns: string[]; row_count: number; first_rows: string[][];
  suggested: { timestamp_column: string | null; value_column: string | null; unit: string | null } };
type Replay = {
  label: string; digest: string; window: { start: string; end: string; min_mw: number; max_mw: number };
  conversion: { alpha: number; seeds_per_hour: number; scenario_family: string };
  summary: Record<string, { episodes: number; violations: number; safe_recoveries: number; failed_recoveries: number; monitor_stops: number }>;
  by_hour: { hour: string; demand_shape: number; drain_multiplier: number; B: { violations: number; safe: number; n: number }; D: { violations: number; safe: number; n: number } }[];
};

async function send<T>(path: string, init: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = (body as { detail?: unknown }).detail;
    throw new Error(typeof d === "string" ? d : (d as { error?: string })?.error ?? `HTTP ${r.status}`);
  }
  return body as T;
}

function Trend({ ds }: { ds: Dataset }) {
  const pts = ds.trend;
  if (pts.length < 2) return null;
  const W = 760, H = 200, P = 40;
  const t0 = Date.parse(pts[0].t), t1 = Date.parse(pts[pts.length - 1].t);
  const lo = Math.min(...pts.map((p) => p.mw)), hi = Math.max(...pts.map((p) => p.mw));
  const x = (t: string) => P + ((Date.parse(t) - t0) / Math.max(1, t1 - t0)) * (W - 2 * P);
  const y = (v: number) => H - P + 10 - ((v - lo) / Math.max(1, hi - lo)) * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Real demand trend">
      <polyline fill="none" stroke="#a78bfa" strokeWidth="2" points={pts.map((p) => `${x(p.t)},${y(p.mw)}`).join(" ")} />
      <text x={P} y={14} fill="#94a3b8" fontSize="11">{hi.toLocaleString()} MW</text>
      <text x={P} y={H - 2} fill="#94a3b8" fontSize="11">{lo.toLocaleString()} MW · {pts[0].t.replace("T", " ")}</text>
      <text x={W - P} y={H - 2} fill="#94a3b8" fontSize="11" textAnchor="end">{pts[pts.length - 1].t.replace("T", " ")}</text>
    </svg>
  );
}

export function RealDataView() {
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [unit, setUnit] = useState("");
  const [pv, setPv] = useState<Preview | null>(null);
  const [tsCol, setTsCol] = useState("");
  const [valCol, setValCol] = useState("");
  const [ds, setDs] = useState<Dataset | null>(null);
  const [rep, setRep] = useState<Replay | null>(null);
  const [win, setWin] = useState({ start: "", end: "", alpha: 0.3, seeds: 3 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr("");
    try { await fn(); } catch (e) { setErr(String((e as Error).message ?? e)); } finally { setBusy(false); }
  };
  const loaded = (d: Dataset) => {
    setDs(d); setRep(null);
    setWin((w) => ({ ...w, start: String(d.quality.start).slice(0, 16), end: String(d.quality.end).slice(0, 16) }));
  };
  const form = () => { const f = new FormData(); f.append("file", file!); return f; };

  return (
    <div className="space-y-4">
      <div className="panel text-sm text-slate-300">
        <div className="h">Real historical energy data · context and replay only</div>
        <p>Import genuine historical demand or generation data, for example the <b>All-India demand met</b> series from the National Power Portal
          (<a className="text-cyan-300 underline" href="https://npp.gov.in/dashBoard/gc-map-dashboard-meritchart" target="_blank" rel="noreferrer">npp.gov.in dashboard</a>,
          "Download Excel"). These are <b>national grid values in MW</b>, <b>not campus telemetry</b>. They are never fed into battery calculations and are
          never simulator truth. Replay uses only the normalised daily <i>shape</i> to build clearly labelled simulated stress scenarios.</p>
        <button className="btn-p mt-2" disabled={busy} onClick={() => run(async () => loaded(await send<Dataset>("/api/data/sample", { method: "POST" })))}>
          Load bundled real NPP file (2026-10-23)
        </button>
      </div>

      <div className="panel">
        <div className="h">Upload a file (.csv, .xlsx, or NPP .json)</div>
        <div className="flex flex-wrap items-end gap-3">
          <input className="inp" type="file" accept=".csv,.xlsx,.json,.txt" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPv(null); }} />
          <label className="text-xs text-slate-400">Source attribution (required)<br />
            <input className="inp w-80" value={source} maxLength={300} placeholder="e.g. National Power Portal, Demand Met, 2026-10-22" onChange={(e) => setSource(e.target.value)} />
          </label>
          <button className="btn-s" disabled={busy || !file} onClick={() => run(async () => {
            const p = await send<Preview>("/api/data/preview", { method: "POST", body: form() });
            setPv(p); setTsCol(p.suggested.timestamp_column ?? ""); setValCol(p.suggested.value_column ?? ""); setUnit(p.suggested.unit ?? "");
          })}>Preview</button>
        </div>
        {pv && (
          <div className="mt-3 space-y-2 text-sm">
            <div className="text-xs text-slate-400">{pv.format.toUpperCase()} · {pv.row_count} rows · columns: {pv.columns.join(", ")}</div>
            <div className="overflow-x-auto"><table className="text-xs"><thead><tr>{pv.columns.map((c) => <th key={c} className="pr-3 text-left text-slate-400">{c}</th>)}</tr></thead>
              <tbody>{pv.first_rows.slice(0, 5).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="mono pr-3">{c}</td>)}</tr>)}</tbody></table></div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-slate-400">Timestamp column<br /><select className="inp" value={tsCol} onChange={(e) => setTsCol(e.target.value)}>
                <option value="">—</option>{pv.columns.map((c) => <option key={c}>{c}</option>)}</select></label>
              <label className="text-xs text-slate-400">Value column<br /><select className="inp" value={valCol} onChange={(e) => setValCol(e.target.value)}>
                <option value="">—</option>{pv.columns.map((c) => <option key={c}>{c}</option>)}</select></label>
              <label className="text-xs text-slate-400">Unit<br /><select className="inp" value={unit} onChange={(e) => setUnit(e.target.value)}>
                <option value="">choose…</option><option>MW</option><option>GW</option><option value="KW">kW</option></select></label>
              <button className="btn-p" disabled={busy || !tsCol || !valCol || !unit || !source.trim()} onClick={() => run(async () => {
                const f = form(); f.append("source", source); f.append("timestamp_column", tsCol); f.append("value_column", valCol); f.append("unit", unit);
                loaded(await send<Dataset>("/api/data/import", { method: "POST", body: f }));
              })}>Validate & import</button>
            </div>
          </div>
        )}
      </div>

      {err && <div className="panel !py-2 text-sm text-rose-300">Rejected: {err}</div>}

      {ds && (
        <div className="panel space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h !mb-0">{ds.name}</div><Badge tone="info">REAL HISTORICAL DATA</Badge><Badge tone="mute">{ds.kind}</Badge>
          </div>
          <div className="text-xs text-slate-400">Source: {ds.source} · file {ds.filename} · SHA-256 <span className="mono">{ds.sha256.slice(0, 16)}</span> · unit in file {ds.unit_in} → MW</div>
          <Trend ds={ds} />
          <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            {Object.entries(ds.quality).map(([k, v]) => <div key={k} className="rounded-md border border-slate-800 p-2"><div className="text-slate-500">{k.replace(/_/g, " ")}</div><div className="mono text-slate-200">{String(v)}</div></div>)}
          </div>
        </div>
      )}

      {ds && (
        <div className="panel space-y-3">
          <div className="h">Replay as simulated stress scenarios</div>
          <p className="text-xs text-slate-400">Each hour's normalised demand shape p (0 = window minimum, 1 = window maximum) sets an <b>assumed</b> unmodelled campus drain multiplier
            1 + α·p on the design scenario. The agent never sees the real data. Results are reported separately from every benchmark.</p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-slate-400">Start<br /><input className="inp" type="datetime-local" value={win.start} onChange={(e) => setWin({ ...win, start: e.target.value })} /></label>
            <label className="text-xs text-slate-400">End<br /><input className="inp" type="datetime-local" value={win.end} onChange={(e) => setWin({ ...win, end: e.target.value })} /></label>
            <label className="text-xs text-slate-400">α (extra drain at peak)<br /><input className="inp w-24" type="number" step={0.05} min={0} max={0.5} value={win.alpha} onChange={(e) => setWin({ ...win, alpha: Number(e.target.value) })} /></label>
            <label className="text-xs text-slate-400">Seeds per hour<br /><input className="inp w-20" type="number" min={1} max={10} value={win.seeds} onChange={(e) => setWin({ ...win, seeds: Number(e.target.value) })} /></label>
            <button className="btn-p" disabled={busy} onClick={() => run(async () => setRep(await send<Replay>(`/api/data/datasets/${ds.id}/replay`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ start: win.start ? `${win.start}:00` : null, end: win.end ? `${win.end}:59` : null, alpha: win.alpha, seeds_per_hour: win.seeds }) })))}>
              {busy ? "Running…" : "▶ Run replay"}</button>
            {rep && <a className="btn-s" href="/api/data/replay/latest.csv" download="aegis-real-demand-replay.csv">Download CSV</a>}
          </div>
          {rep && (
            <>
              <div className="rounded-md border border-fuchsia-800 bg-fuchsia-950/30 p-2 text-xs text-fuchsia-200">{rep.label}</div>
              <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-400"><th>Arm</th><th>Episodes</th><th>Violations</th><th>Safe recoveries</th><th>Failed recoveries</th><th>Monitor stops</th></tr></thead>
                <tbody>{Object.entries(rep.summary).map(([a, s]) => <tr key={a} className="border-t border-slate-800"><td className="py-1">{a === "D" ? "D Full AEGIS" : "B Basic tool-using"}</td>
                  <td className="mono">{s.episodes}</td><td className={`mono ${s.violations ? "text-rose-300" : ""}`}>{s.violations}</td><td className="mono">{s.safe_recoveries}</td><td className="mono">{s.failed_recoveries}</td><td className="mono">{s.monitor_stops}</td></tr>)}</tbody></table>
              <div className="max-h-72 overflow-auto"><table className="w-full text-xs"><thead><tr className="text-left text-slate-400"><th>Hour</th><th>Demand shape p</th><th>Drain ×</th><th>D safe / n</th><th>D viol.</th><th>B viol.</th></tr></thead>
                <tbody>{rep.by_hour.map((h) => <tr key={h.hour} className="border-t border-slate-800"><td className="mono py-0.5">{h.hour.replace("T", " ").slice(0, 16)}</td><td className="mono">{h.demand_shape.toFixed(2)}</td>
                  <td className="mono">{h.drain_multiplier.toFixed(3)}</td><td className="mono">{h.D.safe}/{h.D.n}</td><td className="mono">{h.D.violations}</td><td className="mono">{h.B.violations}</td></tr>)}</tbody></table></div>
              <div className="text-[11px] text-slate-500">Window {rep.window.start} → {rep.window.end} ({rep.window.min_mw.toLocaleString()}–{rep.window.max_mw.toLocaleString()} MW, used only for normalisation) · α {rep.conversion.alpha} · digest <span className="mono">{rep.digest}</span></div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

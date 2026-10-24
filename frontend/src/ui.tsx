import type { ReactNode } from "react";

/** Shared AEGIS UI primitives. Line icons: 24px grid, 1.75 stroke, rendered at 16px unless sized. */
const P: Record<string, string> = {
  campus: "M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6M9 11h.01M15 11h.01",
  console: "M4 5h16v14H4zM8 10l3 2-3 2M13 15h3",
  bench: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  shadow: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  record: "M7 3h7l5 5v13H7zM14 3v5h5M10 13l2 2 3-4",
  shield: "M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6l8-3zM9 12l2 2 4-4",
  lock: "M6 11h12v9H6zM9 11V8a3 3 0 016 0v3",
  warn: "M12 4l9 16H3L12 4zM12 10v4M12 17h.01",
  check: "M5 12.5l4.5 4.5L19 7.5",
  cross: "M6 6l12 12M18 6L6 18",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
  arrow: "M5 12h14M13 6l6 6-6 6",
  bolt: "M13 3L5 14h6l-1 7 8-11h-6l1-7z",
};

export function Icon({ name, size = 16, className = "" }: { name: keyof typeof P | string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`shrink-0 ${className}`}>
      <path d={P[name] ?? P.shield} />
    </svg>
  );
}

export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <defs><linearGradient id="bm" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#5b52e8" /><stop offset="1" stopColor="#0ea5a8" /></linearGradient></defs>
      <rect width="40" height="40" rx="11" fill="url(#bm)" />
      <path d="M20 8l10 3.6v7.4c0 5.4-4 9.6-10 11-6-1.4-10-5.6-10-11v-7.4L20 8z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
      <path d="M20 12v14M20 19l-5 4M20 19l5 4" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export function PageHeader({ eyebrow, title, children, action }: { eyebrow?: string; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rise flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-3xl">
        {eyebrow && <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-400">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold text-slate-100 md:text-[1.7rem]">{title}</h1>
        {children && <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{children}</p>}
      </div>
      {action}
    </div>
  );
}

/** Provenance chip: keeps measured, simulated and assumed data visibly distinct everywhere. */
export function Provenance({ kind }: { kind: "measured" | "simulated" | "assumed" }) {
  const m = {
    measured: ["Measured · real national data", "border-emerald-700 bg-emerald-950 text-emerald-300"],
    simulated: ["Simulated", "border-cyan-700 bg-cyan-950 text-cyan-300"],
    assumed: ["Assumed · not validated", "border-amber-700 bg-amber-950 text-amber-300"],
  }[kind];
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${m[1]}`}>{m[0]}</span>;
}

export function Metric({ label, value, sub, kind, tone = "default" }: {
  label: string; value: ReactNode; sub?: ReactNode; kind?: "measured" | "simulated" | "assumed"; tone?: "default" | "risk" | "ok" | "warn";
}) {
  const t = { default: "text-slate-100", risk: "text-rose-300", ok: "text-emerald-300", warn: "text-amber-300" }[tone];
  return (
    <div className="rounded-xl border border-slate-700/70 bg-white p-3.5 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">{label}</div>
        {kind && <Provenance kind={kind} />}
      </div>
      <div className={`mono mt-1.5 text-2xl font-semibold ${t}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export function Banner({ tone, icon, title, children }: { tone: "info" | "warn" | "risk" | "ok"; icon?: string; title?: string; children: ReactNode }) {
  const c = {
    info: "border-cyan-700 bg-cyan-950 text-cyan-200", warn: "border-amber-700 bg-amber-950 text-amber-200",
    risk: "border-rose-700 bg-rose-950 text-rose-200", ok: "border-emerald-700 bg-emerald-950 text-emerald-200",
  }[tone];
  return (
    <div role={tone === "risk" ? "alert" : "note"} className={`flex gap-2.5 rounded-xl border p-3 text-sm ${c}`}>
      <Icon name={icon ?? (tone === "ok" ? "check" : tone === "info" ? "shield" : "warn")} size={18} className="mt-0.5" />
      <div>{title && <div className="font-semibold">{title}</div>}<div className="leading-relaxed">{children}</div></div>
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%" }: { h?: number; w?: string }) {
  return <div className="animate-pulse rounded-md bg-slate-800" style={{ height: h, width: w }} aria-hidden="true" />;
}

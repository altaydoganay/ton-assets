"use client";
import { useState } from "react";
import { Check, Copy, AlertTriangle, HelpCircle } from "lucide-react";

export function StatCard({
  label, value, hint, accent, tone, icon,
}: {
  label: string; value: React.ReactNode; hint?: string; accent?: string;
  tone?: string; icon?: React.ReactNode;
}) {
  // tone => kart rengi (üst şerit + zemin + ikon); accent => sayı rengi
  return (
    <div className="stat shine" style={tone ? ({ ["--tone" as any]: tone }) : undefined}>
      {icon && <div className="stat-ico">{icon}</div>}
      <div className="text-[11px] font-semibold uppercase tracking-wide muted">{label}</div>
      <div className="font-display tabular mt-1 text-2xl font-extrabold tracking-tight"
        style={{ color: accent || tone || undefined }}>{value}</div>
      {hint && <div className="mt-1 text-xs muted">{hint}</div>}
    </div>
  );
}

export function Meter({ value, max, color }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const c = color || (pct > 85 ? "#ef4444" : pct > 60 ? "#f59e0b" : "#10b981");
  return (
    <div className="meter">
      <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, background: c }} />
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn-ghost"
      onClick={() => { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}
      title="Kopyala"
    >
      {done ? <Check size={13} /> : <Copy size={13} />}
      {label && <span>{label}</span>}
    </button>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="card space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 18, width: `${60 + (i % 4) * 10}%` }} />
      ))}
    </div>
  );
}

export function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  );
}

export function InfoTip({ title, children }: { title?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        className="ml-1 inline-grid h-5 w-5 place-items-center rounded-full border text-[11px] font-bold muted hover:text-brand"
        style={{ borderColor: "var(--border)", background: "var(--bg2)" }}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}
        title="Açıklama"
      >
        <HelpCircle size={13} />
      </button>
      {open && (
        <span
          className="absolute left-0 top-6 z-50 w-72 rounded-xl border p-3 text-left text-xs shadow-xl"
          style={{ background: "var(--card)", borderColor: "var(--border)", color: "var(--fg)" }}
        >
          {title && <b className="mb-1 block text-sm">{title}</b>}
          <span className="leading-relaxed muted">{children}</span>
        </span>
      )}
    </span>
  );
}

export function Callout({ kind = "warn", children }: { kind?: "warn" | "info"; children: React.ReactNode }) {
  const color = kind === "warn" ? "#f59e0b" : "#38bdf8";
  return (
    <div className="card flex items-start gap-3" style={{ borderColor: color + "66" }}>
      <AlertTriangle size={18} style={{ color }} className="mt-0.5 shrink-0" />
      <div className="text-sm">{children}</div>
    </div>
  );
}

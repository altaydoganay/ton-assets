"use client";
import { useState } from "react";
import { Check, Copy, AlertTriangle } from "lucide-react";

export function StatCard({
  label, value, hint, accent,
}: { label: string; value: React.ReactNode; hint?: string; accent?: string }) {
  return (
    <div className="card card-hover">
      <div className="text-xs muted">{label}</div>
      <div className="mt-1 text-2xl font-bold" style={accent ? { color: accent } : undefined}>{value}</div>
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

export function Callout({ kind = "warn", children }: { kind?: "warn" | "info"; children: React.ReactNode }) {
  const color = kind === "warn" ? "#f59e0b" : "#38bdf8";
  return (
    <div className="card flex items-start gap-3" style={{ borderColor: color + "66" }}>
      <AlertTriangle size={18} style={{ color }} className="mt-0.5 shrink-0" />
      <div className="text-sm">{children}</div>
    </div>
  );
}

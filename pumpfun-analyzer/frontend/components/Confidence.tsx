"use client";

export function Confidence({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const label = pct >= 70 ? "Yüksek" : pct >= 40 ? "Orta" : "Düşük";
  const color = pct >= 70 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full" style={{ background: "var(--border)" }}>
        <div className="h-1.5 rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs muted">Güven: {label} (%{pct})</span>
    </div>
  );
}

export function PageHeader({
  title, subtitle, action, icon,
}: { title: string; subtitle?: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="page-band mb-5 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {icon && <div className="page-band-ico grid h-11 w-11 shrink-0 place-items-center rounded-2xl">{icon}</div>}
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="muted text-sm mt-1 max-w-2xl">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

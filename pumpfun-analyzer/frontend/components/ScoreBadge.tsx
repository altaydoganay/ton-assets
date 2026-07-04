"use client";
import clsx from "clsx";

export function ScoreBadge({ score }: { score?: number | null }) {
  if (score === null || score === undefined)
    return <span className="badge muted">—</span>;
  // TradeFable skor stili: mini ilerleme barı + mono skor (token/cüzdan tablosu)
  const tone = score >= 70 ? "var(--emerald)" : score >= 50 ? "var(--amber)" : "var(--rose)";
  return (
    <span className="inline-flex items-center gap-2 align-middle">
      <span className="inline-block h-[5px] w-10 overflow-hidden rounded-full"
        style={{ background: "color-mix(in srgb, var(--muted) 22%, transparent)" }}>
        <span className="block h-full rounded-full"
          style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: tone }} />
      </span>
      <span className="font-mono text-xs font-bold tabular-nums" style={{ color: tone }}>{score.toFixed(0)}</span>
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    tracked: "bg-emerald-500/15 text-emerald-500",
    discovered: "bg-sky-500/15 text-sky-500",
    analyzed: "bg-slate-500/15 text-slate-400",
    below_threshold: "bg-amber-500/15 text-amber-500",
    rejected: "bg-red-500/15 text-red-500",
    vetoed: "bg-red-500/15 text-red-500",
    blocked: "bg-red-700/20 text-red-400",
  };
  const labels: Record<string, string> = {
    tracked: "Takipte", discovered: "Keşfedildi", analyzed: "Analiz edildi",
    below_threshold: "Eşik altında", rejected: "Elendi", vetoed: "Veto", blocked: "Engelli",
  };
  return <span className={clsx("badge", map[status] || "muted")}>{labels[status] || status}</span>;
}

export function RiskFlags({ flags }: { flags?: string[] }) {
  if (!flags || flags.length === 0)
    return <span className="text-xs text-emerald-500">Belirgin uyarı yok</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((f, i) => (
        <span key={i} className="badge bg-red-500/15 text-red-500">{f}</span>
      ))}
    </div>
  );
}

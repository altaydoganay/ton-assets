"use client";
import Link from "next/link";
import useSWR from "swr";
import { CheckCircle2, XCircle, LogOut, Info, ArrowRight } from "lucide-react";
import { fetcher } from "@/lib/api";
import { TokenAvatar, useTokenMeta } from "./TokenAvatar";
import { InfoTip } from "./ui";

type Decision = {
  id: number; action: "opened" | "blocked" | "exit" | "info";
  reason: string; token?: string | null; token_score?: number | null; created_at?: string;
};

const ACTION: Record<string, { label: string; cls: string; icon: any }> = {
  opened: { label: "PAPER ALDI", cls: "text-emerald-500 bg-emerald-500/12", icon: CheckCircle2 },
  blocked: { label: "ALMADI", cls: "text-amber-500 bg-amber-500/12", icon: XCircle },
  exit: { label: "ÇIKIŞ", cls: "text-sky-500 bg-sky-500/12", icon: LogOut },
  info: { label: "BİLGİ", cls: "text-slate-400 bg-slate-500/12", icon: Info },
};

function scoreTone(s?: number | null) {
  if (s == null) return "var(--muted)";
  if (s >= 75) return "var(--emerald)";
  if (s >= 55) return "var(--amber)";
  return "var(--rose)";
}
function ago(iso?: string) {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}sn`;
  if (s < 3600) return `${Math.floor(s / 60)}dk`;
  return `${Math.floor(s / 3600)}sa`;
}

export function AiDecisionFlow({ strategy = "ai", limit = 7 }: { strategy?: "ai" | "copy"; limit?: number }) {
  const { data } = useSWR<Decision[]>(`/trading/decisions?strategy=${strategy}&limit=${limit}`, fetcher, { refreshInterval: 6000 });
  const rows = (data || []).slice(0, limit);
  const meta = useTokenMeta(rows.map((r) => r.token));

  return (
    <div className="premium-chart-card">
      <div className="mb-3 flex items-center justify-between">
        <b className="flex items-center gap-2">
          {strategy === "ai" ? "AI Karar Akışı" : "Copy Karar Akışı"}
          <InfoTip title="Karar akışı">Motor her sinyalde token'ı neden aldı ya da hangi kapıda durdu — token skoru ve sebebiyle.</InfoTip>
        </b>
        <Link href="/logs" className="text-xs muted hover:opacity-100">Tümü <ArrowRight size={12} className="inline" /></Link>
      </div>
      {rows.length === 0 ? (
        <div className="py-8 text-center text-sm muted">Motor çalışıp sinyal geldikçe kararlar burada akar.</div>
      ) : (
        <div className="space-y-1.5">
          {rows.map((d) => {
            const a = ACTION[d.action] || ACTION.info;
            const m = d.token ? meta[d.token] : undefined;
            return (
              <div key={d.id} className="flex items-center gap-3 rounded-xl border px-2.5 py-2" style={{ borderColor: "var(--border)" }}>
                <TokenAvatar mint={d.token || undefined} meta={m} size={34} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold">{m?.symbol || m?.name || (d.token ? d.token.slice(0, 4) + "…" : "—")}</span>
                    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${a.cls}`}>{a.label}</span>
                  </div>
                  <div className="truncate text-[11px] muted">{d.reason}</div>
                </div>
                {d.token_score != null && (
                  <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold"
                    style={{ color: scoreTone(d.token_score), border: `2px solid ${scoreTone(d.token_score)}` }}>
                    {Math.round(d.token_score)}
                  </div>
                )}
                <span className="w-8 shrink-0 text-right text-[11px] muted">{ago(d.created_at)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

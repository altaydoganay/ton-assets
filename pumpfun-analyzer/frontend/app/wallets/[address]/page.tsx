"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { solscanAddr } from "@/lib/links";
import { PageHeader, Confidence } from "@/components/Confidence";
import { ScoreBadge, StatusBadge, RiskFlags } from "@/components/ScoreBadge";
import { ScoreChart, SubScoreBars, SubScoreRadar } from "@/components/ScoreChart";
import { EligibilityChecklist } from "@/components/Eligibility";
import { RelationshipGraph } from "@/components/RelationshipGraph";
import { CopyButton, Section } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { Loading, ErrorState } from "@/components/States";
import { ExternalLink, RefreshCw, Ban, Check } from "lucide-react";

export default function WalletDetail() {
  const params = useParams();
  const address = params.address as string;
  const toast = useToast();
  const { data: w, error, isLoading, mutate } = useSWR<any>(`/wallets/${address}`, fetcher);
  const { data: history } = useSWR<any[]>(`/wallets/${address}/score-history`, fetcher);
  const { data: rels } = useSWR<any[]>(`/wallets/${address}/relationships`, fetcher);
  const [busy, setBusy] = useState(false);

  if (isLoading) return <Loading />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!w) return <ErrorState message="Cüzdan bulunamadı" />;

  const latest = w.scores?.[w.scores.length - 1];
  const subScores = latest ? [
    { label: "İşlem Başarısı", value: latest.performance, weight: "%25" },
    { label: "Tutarlılık", value: latest.consistency, weight: "%20" },
    { label: "Risk", value: latest.risk, weight: "%15" },
    { label: "Organik", value: latest.organic, weight: "%15" },
    { label: "Tutma Süresi", value: latest.hold_quality, weight: "%10" },
    { label: "Güvenlik", value: latest.safety, weight: "%10" },
    { label: "Güncellik", value: latest.recency, weight: "%5" },
  ] : [];
  const eligFailures: string[] = latest?.breakdown?.eligibility_failures || [];

  async function action(fn: () => Promise<any>, msg: string) {
    setBusy(true);
    try { await fn(); toast("success", msg); await mutate(); }
    catch (e: any) { toast("error", e?.message || "İşlem başarısız"); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <PageHeader
        title={w.label || shortAddr(w.address)}
        subtitle={w.address}
        action={
          <div className="flex flex-wrap gap-2">
            <a className="btn" href={solscanAddr(w.address)} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Solscan</a>
            <button className="btn" disabled={busy} onClick={() => action(() => apiSend(`/wallets/${address}/reanalyze`, "POST"), "Yeniden analiz edildi")}><RefreshCw size={15} /> Yeniden Analiz</button>
            <button className="btn" disabled={busy} onClick={() => action(() => apiSend(`/wallets/${address}/approve`, "POST"), "Cüzdan onaylandı")}><Check size={15} /> Onayla</button>
            <button className="btn-danger" disabled={busy} onClick={() => action(() => apiSend(`/wallets/${address}/block`, "POST"), "Cüzdan engellendi")}><Ban size={15} /> Engelle</button>
          </div>
        }
      />

      <div className="mb-3 flex items-center gap-2"><CopyButton text={w.address} label="Adresi kopyala" /></div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="flex items-center justify-between">
            <span className="muted text-sm">Toplam Puan</span><ScoreBadge score={w.latest_score} />
          </div>
          <div className="mt-3"><StatusBadge status={w.status} /></div>
          <div className="mt-3"><Confidence value={w.confidence} /></div>
          <div className="mt-3"><RiskFlags flags={w.risk_flags} /></div>
          {subScores.length > 0 && <div className="mt-2"><SubScoreRadar data={subScores} /></div>}
        </div>

        <Section title="Puan Kırılımı">
          {subScores.length ? <SubScoreBars scores={subScores} /> : <p className="muted text-sm">Henüz puanlanmadı.</p>}
        </Section>

        <Section title="Kabul / Ret Kriterleri">
          {latest ? (
            <>
              <EligibilityChecklist failures={eligFailures} />
              <div className="mt-3 text-xs muted">
                {w.status === "tracked" ? "✅ Tüm kriterler sağlandı ve puan ≥70 → takip ediliyor."
                  : eligFailures.length ? "Kırmızı maddeler yüzünden takip edilmiyor (puan yüksek olsa bile)."
                  : "Kriterler tamam; takip için puan ≥70 ve veto olmaması gerekir."}
              </div>
            </>
          ) : <p className="muted text-sm">Henüz analiz edilmedi.</p>}
        </Section>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Metrikler">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Metric label="Kapalı Pozisyon" value={w.metrics?.closed_positions} />
            <Metric label="Açık Pozisyon" value={w.metrics?.open_positions} />
            <Metric label="Başarı Oranı" value={w.metrics?.win_rate !== undefined ? `%${Math.round(w.metrics.win_rate * 100)}` : undefined} />
            <Metric label="Profit Factor" value={w.metrics?.profit_factor} />
            <Metric label="Gerçekleşen PnL (SOL)" value={w.metrics?.realized_pnl_sol} />
            <Metric label="Token Çeşitliliği" value={w.metrics?.token_diversity} />
            <Metric label="Medyan Tutma (dk)" value={w.metrics?.median_hold_seconds ? Math.round(w.metrics.median_hold_seconds / 60) : undefined} />
            <Metric label="Geçmiş (gün)" value={w.metrics?.history_days ? Math.round(w.metrics.history_days) : undefined} />
          </div>
        </Section>
        <Section title="Puan Geçmişi">
          {history && history.length > 1 ? <ScoreChart data={history} />
            : <p className="muted text-sm py-8 text-center">Grafik için en az iki puan kaydı gerekiyor.</p>}
        </Section>
      </div>

      {latest?.veto_reasons?.length > 0 && (
        <div className="card mt-4" style={{ borderColor: "#ef444466" }}>
          <h2 className="mb-2 font-semibold text-red-500">Veto Nedenleri</h2>
          <ul className="list-disc pl-5 text-sm">{latest.veto_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}

      <div className="mt-4">
        <Section title="Bağlantılı Cüzdanlar (sybil / insider / copy kümeleri)">
          <RelationshipGraph center={w.address} rels={rels || []} />
        </Section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: number | string }) {
  return (
    <div>
      <div className="muted text-xs">{label}</div>
      <div className="font-medium">{typeof value === "number" ? fmtNum(value, 4) : value ?? "—"}</div>
    </div>
  );
}

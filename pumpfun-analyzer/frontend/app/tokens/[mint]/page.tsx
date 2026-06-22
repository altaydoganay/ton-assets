"use client";
import { use } from "react";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { PageHeader, Confidence } from "@/components/Confidence";
import { ScoreBadge, StatusBadge, RiskFlags } from "@/components/ScoreBadge";
import { ScoreChart, SubScoreBars } from "@/components/ScoreChart";
import { Loading, ErrorState } from "@/components/States";

export default function TokenDetail({ params }: { params: Promise<{ mint: string }> }) {
  const { mint } = use(params);
  const { data: t, error, isLoading, mutate } = useSWR<any>(`/tokens/${mint}`, fetcher);
  const { data: history } = useSWR<any[]>(`/tokens/${mint}/score-history`, fetcher);
  const { data: holders } = useSWR<any[]>(`/tokens/${mint}/holders`, fetcher);

  if (isLoading) return <Loading />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!t) return <ErrorState message="Token bulunamadı" />;

  const latest = t.scores?.[t.scores.length - 1];
  const subScores = latest
    ? [
        { label: "Zincir Üstü Güvenlik", value: latest.security, weight: "%30" },
        { label: "Holder Dağılımı", value: latest.holder_distribution, weight: "%20" },
        { label: "Creator Geçmişi", value: latest.creator_history, weight: "%15" },
        { label: "Likidite & Piyasa", value: latest.liquidity_quality, weight: "%15" },
        { label: "Organik Büyüme", value: latest.organic_growth, weight: "%10" },
        { label: "İşlem Davranışı", value: latest.trade_behavior, weight: "%10" },
      ]
    : [];

  return (
    <div>
      <PageHeader
        title={t.symbol || t.name || shortAddr(t.mint)}
        subtitle={t.mint}
        action={
          <div className="flex gap-2">
            <button className="btn" onClick={() => mutate()}>Yeniden Analiz</button>
            <button className="btn" onClick={() => apiSend(`/tokens/${mint}/block`, "POST").then(() => mutate())}>Engelle</button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="flex items-center justify-between">
            <span className="muted text-sm">Toplam Puan</span>
            <ScoreBadge score={t.latest_score} />
          </div>
          <div className="mt-3"><StatusBadge status={t.status} /></div>
          <div className="mt-3"><Confidence value={t.confidence} /></div>
          <div className="mt-3"><RiskFlags flags={t.risk_flags} /></div>
        </div>
        <div className="card lg:col-span-2">
          <h2 className="mb-3 font-semibold">Puan Kırılımı (yaşa/aşamaya uyarlanmış)</h2>
          {subScores.length ? <SubScoreBars scores={subScores} /> : <p className="muted text-sm">Henüz puanlanmadı.</p>}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-semibold">Piyasa & Güvenlik</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Metric label="Likidite (SOL)" value={t.metrics?.liquidity_sol} />
            <Metric label="Piyasa Değeri ($)" value={t.metrics?.market_cap_usd} />
            <Metric label="24s Hacim ($)" value={t.metrics?.volume_24h_usd} />
            <Metric label="Benzersiz Holder" value={t.metrics?.unique_holders} />
            <Metric label="İlk 10 Yoğunluk" value={t.metrics?.top10_pct !== undefined ? `%${Math.round(t.metrics.top10_pct * 100)}` : undefined} />
            <Metric label="Insider Arz" value={t.metrics?.insider_supply_pct !== undefined ? `%${Math.round(t.metrics.insider_supply_pct * 100)}` : undefined} />
          </div>
        </div>
        <div className="card">
          <h2 className="mb-3 font-semibold">Puan Geçmişi</h2>
          {history && history.length > 1 ? (
            <ScoreChart data={history} />
          ) : (
            <p className="muted text-sm py-8 text-center">Grafik için en az iki puan kaydı gerekiyor.</p>
          )}
        </div>
      </div>

      <div className="card mt-4">
        <h2 className="mb-3 font-semibold">Holder Dağılımı</h2>
        {holders && holders.length > 0 ? (
          <table className="w-full text-sm">
            <thead><tr className="text-left muted"><th>#</th><th>Adres</th><th>Pay</th><th>Tür</th></tr></thead>
            <tbody>
              {holders.slice(0, 20).map((h) => (
                <tr key={h.address}>
                  <td>{h.rank}</td>
                  <td>{shortAddr(h.address)}</td>
                  <td>%{(h.pct * 100).toFixed(1)}</td>
                  <td className="muted">{h.is_system ? "Sistem/LP" : h.is_insider ? "Insider" : "Yatırımcı"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted text-sm">Holder verisi yok. (LP, bonding curve ve sistem cüzdanları hesaplamadan ayrılır.)</p>
        )}
      </div>

      {latest?.veto_reasons?.length > 0 && (
        <div className="card mt-4 border-red-500/40">
          <h2 className="mb-2 font-semibold text-red-500">Kritik Veto Nedenleri</h2>
          <ul className="list-disc pl-5 text-sm">
            {latest.veto_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: number | string }) {
  return (
    <div>
      <div className="muted text-xs">{label}</div>
      <div className="font-medium">{typeof value === "number" ? fmtNum(value, 2) : value ?? "—"}</div>
    </div>
  );
}

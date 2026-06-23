"use client";
import { use, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { PageHeader, Confidence } from "@/components/Confidence";
import { ScoreBadge, StatusBadge, RiskFlags } from "@/components/ScoreBadge";
import { ScoreChart, SubScoreBars } from "@/components/ScoreChart";
import { Loading, ErrorState } from "@/components/States";

export default function WalletDetail({ params }: { params: Promise<{ address: string }> }) {
  const { address } = use(params);
  const { data: w, error, isLoading, mutate } = useSWR<any>(`/wallets/${address}`, fetcher);
  const { data: history } = useSWR<any[]>(`/wallets/${address}/score-history`, fetcher);
  const { data: rels } = useSWR<any[]>(`/wallets/${address}/relationships`, fetcher);
  const [reanalyzing, setReanalyzing] = useState(false);

  if (isLoading) return <Loading />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!w) return <ErrorState message="Cüzdan bulunamadı" />;

  const latest = w.scores?.[w.scores.length - 1];
  const subScores = latest
    ? [
        { label: "İşlem Başarısı", value: latest.performance, weight: "%25" },
        { label: "Tutarlılık", value: latest.consistency, weight: "%20" },
        { label: "Risk & Düşüş", value: latest.risk, weight: "%15" },
        { label: "Organik Davranış", value: latest.organic, weight: "%15" },
        { label: "Tutma Süresi", value: latest.hold_quality, weight: "%10" },
        { label: "Rug/Copy/Insider Güvenliği", value: latest.safety, weight: "%10" },
        { label: "Güncellik", value: latest.recency, weight: "%5" },
      ]
    : [];

  async function reanalyze() {
    setReanalyzing(true);
    try {
      // Zincirden güncel işlemleri çekip yeniden puanlar.
      await apiSend(`/wallets/${address}/reanalyze`, "POST");
    } catch {
      /* hata durumunda mevcut veriyi koru */
    } finally {
      await mutate();
      setReanalyzing(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={w.label || shortAddr(w.address)}
        subtitle={w.address}
        action={
          <div className="flex gap-2">
            <button className="btn" onClick={reanalyze} disabled={reanalyzing}>{reanalyzing ? "Analiz ediliyor…" : "Yeniden Analiz"}</button>
            <button className="btn" onClick={() => apiSend(`/wallets/${address}/approve`, "POST").then(() => mutate())}>Onayla</button>
            <button className="btn" onClick={() => apiSend(`/wallets/${address}/block`, "POST").then(() => mutate())}>Engelle</button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="flex items-center justify-between">
            <span className="muted text-sm">Toplam Puan</span>
            <ScoreBadge score={w.latest_score} />
          </div>
          <div className="mt-3"><StatusBadge status={w.status} /></div>
          <div className="mt-3"><Confidence value={w.confidence} /></div>
          <div className="mt-3"><RiskFlags flags={w.risk_flags} /></div>
        </div>

        <div className="card lg:col-span-2">
          <h2 className="mb-3 font-semibold">Puan Kırılımı</h2>
          {subScores.length ? <SubScoreBars scores={subScores} /> : <p className="muted text-sm">Henüz puanlanmadı.</p>}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-semibold">Metrikler</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Metric label="Kapalı Pozisyon" value={w.metrics?.closed_positions} />
            <Metric label="Açık Pozisyon" value={w.metrics?.open_positions} />
            <Metric label="Başarı Oranı" value={w.metrics?.win_rate !== undefined ? `%${Math.round(w.metrics.win_rate * 100)}` : undefined} />
            <Metric label="Profit Factor" value={w.metrics?.profit_factor} />
            <Metric label="Gerçekleşen PnL (SOL)" value={w.metrics?.realized_pnl_sol} />
            <Metric label="Token Çeşitliliği" value={w.metrics?.token_diversity} />
            <Metric label="Medyan Tutma (sn)" value={w.metrics?.median_hold_seconds} />
            <Metric label="Geçmiş (gün)" value={w.metrics?.history_days} />
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

      {latest?.veto_reasons?.length > 0 && (
        <div className="card mt-4 border-red-500/40">
          <h2 className="mb-2 font-semibold text-red-500">Veto / Ret Nedenleri</h2>
          <ul className="list-disc pl-5 text-sm">
            {latest.veto_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <div className="card mt-4">
        <h2 className="mb-3 font-semibold">Bağlantılı Cüzdanlar</h2>
        {rels && rels.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {rels.map((r, i) => (
              <li key={i} className="flex justify-between">
                <span>{shortAddr(r.source)} → {shortAddr(r.target)} <span className="muted">({r.kind})</span></span>
                <span className="muted">Güven: %{Math.round(r.confidence * 100)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted text-sm">Bağlantılı cüzdan tespit edilmedi.</p>
        )}
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

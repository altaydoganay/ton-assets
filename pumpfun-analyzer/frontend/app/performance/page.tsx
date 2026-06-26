"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend, API_URL } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { StatCard, Section } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { Loading } from "@/components/States";
import { Download, TrendingUp, Target, Trophy, Flame } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

const tip = { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 };

export default function Performance() {
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 20000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 15000 });
  const { data: copy, mutate: mutCopy } = useSWR<any[]>("/trading/copy-performance", fetcher, { refreshInterval: 20000 });
  const [amts, setAmts] = useState<Record<string, string>>({});
  const toast = useToast();
  if (!perf) return <Loading />;

  async function saveAmount(addr: string) {
    const v = parseFloat(amts[addr] ?? "");
    try {
      await apiSend(`/wallets/${addr}/copy-amount?sol=${isNaN(v) ? 0 : v}`, "POST");
      await mutCopy();
      toast("success", isNaN(v) || v <= 0 ? "Override kaldırıldı (varsayılana döndü)" : `Bu cüzdana ${v} SOL atandı`);
    } catch (e: any) { toast("error", e?.message || "Kaydedilemedi"); }
  }

  return (
    <div>
      <PageHeader
        title="Performans"
        subtitle="Paper işlem sonuçları — kâr/zarar, başarı oranı ve eğri"
        action={<a className="btn" href={`${API_URL}/export/trades.csv`}><Download size={15} /> İşlemleri dışa aktar</a>}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Toplam PnL (SOL)" value={perf.total_pnl_sol.toFixed(3)} icon={<TrendingUp size={18} />}
          tone={perf.total_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)"}
          accent={perf.total_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)"} />
        <StatCard label="Başarı Oranı" value={`%${Math.round((perf.win_rate || 0) * 100)}`} tone="var(--sky)" icon={<Target size={18} />}
          hint={`${perf.wins}K / ${perf.losses}Z`} />
        <StatCard label="En İyi İşlem" value={perf.best_sol.toFixed(3)} tone="var(--emerald)" accent="var(--emerald)" icon={<Trophy size={18} />} />
        <StatCard label="En Kötü İşlem" value={perf.worst_sol.toFixed(3)} tone="var(--rose)" accent="var(--rose)" icon={<Flame size={18} />} />
      </div>

      {sum && (
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Bugün Harcanan" value={`${sum.today_spent_sol} SOL`} />
          <StatCard label="Bugün PnL" value={`${sum.today_realized_pnl_sol} SOL`}
            accent={sum.today_realized_pnl_sol >= 0 ? "#10b981" : "#ef4444"} />
          <StatCard label="Açık Pozisyon" value={sum.open_positions} />
          <StatCard label="Açık Risk" value={`${sum.open_exposure_sol} SOL`} />
        </div>
      )}

      <div className="mt-4">
        <Section title="Kümülatif Paper PnL">
          {perf.curve?.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={perf.curve}>
                <defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0} />
                </linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="t" stroke="var(--muted)" fontSize={11} />
                <YAxis stroke="var(--muted)" fontSize={11} />
                <Tooltip contentStyle={tip} />
                <Area type="monotone" dataKey="pnl" stroke="#2dd4bf" strokeWidth={2} fill="url(#pg)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[260px] items-center justify-center text-sm muted">
              Henüz kapanmış paper işlem yok. Takip edilen cüzdanlar işlem yaptıkça burası dolacak.
            </div>
          )}
        </Section>
      </div>

      <div className="mt-4">
        <Section title="Cüzdan Bazlı Kopya Performansı">
          <p className="text-xs muted mb-3">
            Her takip cüzdanını KOPYALAMANIN bize getirdiği sonuç. Ardışık zarar eşiğini aşan
            cüzdanlar otomatik elenir (kırmızı "Elendi"). En kazandıranlar üstte.
          </p>
          {copy && copy.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left muted">
                  <th className="py-1">Cüzdan</th><th>Durum</th><th>Kapanan</th><th>K / Z</th>
                  <th>Başarı</th><th>Ardışık Zarar</th><th>Ort. Alım</th><th className="text-right">Kopya PnL</th>
                  <th className="text-right">Bana özel SOL</th>
                </tr></thead>
                <tbody>
                  {copy.map((r) => (
                    <tr key={r.wallet} className="border-t" style={{ borderColor: "var(--border)" }}>
                      <td className="py-1.5 font-mono text-xs">{String(r.wallet).slice(0, 4)}…{String(r.wallet).slice(-4)}</td>
                      <td>{r.status === "blocked"
                        ? <span className="badge" style={{ background: "color-mix(in srgb, var(--rose) 16%, transparent)", color: "var(--rose)" }}>Elendi</span>
                        : <span className="badge" style={{ background: "color-mix(in srgb, var(--emerald) 16%, transparent)", color: "var(--emerald)" }}>Takipte</span>}</td>
                      <td>{r.closed_trades}</td>
                      <td>{r.wins}/{r.losses}</td>
                      <td>%{Math.round((r.win_rate || 0) * 100)}</td>
                      <td style={r.consecutive_losses >= 3 ? { color: "var(--rose)", fontWeight: 700 } : {}}>{r.consecutive_losses}</td>
                      <td className="muted">{r.avg_buy_size_sol != null ? `${Number(r.avg_buy_size_sol).toFixed(3)} ◎` : "—"}</td>
                      <td className="text-right font-bold" style={{ color: r.total_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                        {r.total_pnl_sol >= 0 ? "+" : ""}{Number(r.total_pnl_sol).toFixed(4)}
                      </td>
                      <td className="text-right">
                        <span className="inline-flex items-center gap-1">
                          <input className="input !w-20 !py-1 text-right" type="number" step="any"
                            placeholder={r.copy_override_sol != null ? String(r.copy_override_sol) : "varsayılan"}
                            value={amts[r.wallet] ?? ""} onChange={(e) => setAmts({ ...amts, [r.wallet]: e.target.value })} />
                          <button className="btn-ghost" onClick={() => saveAmount(r.wallet)}>Kaydet</button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs muted">
                "Bana özel SOL": o cüzdanı kopyalarken kullanılacak miktar. Boş bırakırsan varsayılan
                (paper modda sabit {sum?.paper_trade_sol ?? "0.01"} SOL) kullanılır. 0 yazıp kaydedersen override kalkar.
              </p>
            </div>
          ) : (
            <p className="text-sm muted py-6 text-center">Henüz kopya işlem verisi yok. İşlemler kapandıkça burası dolacak.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

"use client";
import useSWR from "swr";
import { fetcher, API_URL } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { StatCard, Section } from "@/components/ui";
import { Loading } from "@/components/States";
import { Download } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

const tip = { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 };

export default function Performance() {
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 20000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 15000 });
  if (!perf) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Performans"
        subtitle="Paper işlem sonuçları — kâr/zarar, başarı oranı ve eğri"
        action={<a className="btn" href={`${API_URL}/export/trades.csv`}><Download size={15} /> İşlemleri dışa aktar</a>}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Toplam PnL (SOL)" value={perf.total_pnl_sol.toFixed(3)}
          accent={perf.total_pnl_sol >= 0 ? "#10b981" : "#ef4444"} />
        <StatCard label="Başarı Oranı" value={`%${Math.round((perf.win_rate || 0) * 100)}`}
          hint={`${perf.wins}K / ${perf.losses}Z`} />
        <StatCard label="En İyi İşlem" value={perf.best_sol.toFixed(3)} accent="#10b981" />
        <StatCard label="En Kötü İşlem" value={perf.worst_sol.toFixed(3)} accent="#ef4444" />
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
    </div>
  );
}

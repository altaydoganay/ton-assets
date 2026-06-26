"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, shortAddr } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, StatCard } from "@/components/ui";
import { Loading } from "@/components/States";
import { Coins, TrendingUp, Target } from "lucide-react";

export default function TokenPerformance() {
  const { data } = useSWR<any[]>("/trading/token-performance", fetcher, { refreshInterval: 20000 });
  if (!data) return <Loading />;

  const totalPnl = data.reduce((s, r) => s + (r.realized_pnl_sol || 0), 0);
  const profitable = data.filter((r) => r.realized_pnl_sol > 0).length;
  const losing = data.filter((r) => r.realized_pnl_sol < 0).length;

  return (
    <div>
      <PageHeader title="🪙 Token Performansı"
        subtitle="Bizim aldığımız token'lerin sonucu — hangisi kazandırdı, hangisi kaybettirdi (paper)." />

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Token Sayısı" value={data.length} tone="var(--violet)" icon={<Coins size={18} />} />
        <StatCard label="Toplam Token PnL" value={`${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(3)}`}
          tone={totalPnl >= 0 ? "var(--emerald)" : "var(--rose)"} accent={totalPnl >= 0 ? "var(--emerald)" : "var(--rose)"} icon={<TrendingUp size={18} />} />
        <StatCard label="Kazandıran" value={profitable} tone="var(--emerald)" accent="var(--emerald)" icon={<Target size={18} />} />
        <StatCard label="Kaybettiren" value={losing} tone="var(--rose)" accent="var(--rose)" />
      </div>

      <Section title="Token bazlı sonuç (en kazandıran üstte)">
        {data.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left muted">
                <th className="py-1">Token</th><th>Puan</th><th>Kapanan</th><th>K / Z</th>
                <th>Başarı</th><th>Açık</th><th className="text-right">Token PnL (SOL)</th>
              </tr></thead>
              <tbody className="stagger">
                {data.map((r) => (
                  <tr key={r.mint} className="table-row border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="py-1.5">
                      <Link href={`/tokens/${r.mint}`} className="clickable font-mono text-xs">
                        {r.symbol || shortAddr(r.mint)}
                      </Link>
                    </td>
                    <td>{r.score != null ? Math.round(r.score) : "—"}</td>
                    <td>{r.closed_trades}</td>
                    <td>{r.wins}/{r.losses}</td>
                    <td>%{Math.round((r.win_rate || 0) * 100)}</td>
                    <td>{r.open_qty > 0 ? `${r.open_cost_sol} ◎` : "—"}</td>
                    <td className="text-right font-bold" style={{ color: r.realized_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                      {r.realized_pnl_sol >= 0 ? "+" : ""}{Number(r.realized_pnl_sol).toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm muted">Henüz token işlemi yok. Takip cüzdanları alım yaptıkça burası dolacak.</p>
        )}
      </Section>
    </div>
  );
}

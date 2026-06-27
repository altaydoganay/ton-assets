"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { StatCard } from "@/components/ui";
import { CountUp } from "@/components/CountUp";
import { EmptyState } from "@/components/EmptyState";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";
import { Wallet, TrendingUp, Flame, Snowflake, Coins } from "lucide-react";

export default function Positions() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const { data: positions, mutate } = useSWR<any[]>("/stats/positions", fetcher, { refreshInterval: 8000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 8000 });
  const [busy, setBusy] = useState<string>("");

  const totalUnreal = (positions || []).reduce((a, p) => a + (p.unrealized_pnl_sol ?? 0), 0);
  const haveLive = (positions || []).some((p) => p.unrealized_pnl_sol != null);

  async function sell(p: any, fraction: number) {
    const pct = Math.round(fraction * 100);
    const pnlNow = p.unrealized_pnl_sol != null
      ? ` Şu anki PnL: ${p.unrealized_pnl_sol >= 0 ? "+" : ""}${fmtNum(p.unrealized_pnl_sol, 4)} SOL (%${Math.round((p.unrealized_pnl_pct ?? 0) * 100)}).`
      : "";
    const ok = await confirm({
      title: `Pozisyonun %${pct}'ini sat`,
      body: `${shortAddr(p.token_mint)} pozisyonunun %${pct}'i CANLI piyasa fiyatından (paper) satılacak.${pnlNow}`,
      confirmText: `Evet, %${pct} sat`, danger: fraction === 1,
    });
    if (!ok) return;
    setBusy(p.token_mint + fraction);
    try {
      const r: any = await apiSend(`/stats/positions/${p.token_mint}/sell?fraction=${fraction}`, "POST");
      await mutate();
      toast(r.realized_pnl_sol >= 0 ? "success" : "info",
        `%${pct} satıldı · PnL ${r.realized_pnl_sol >= 0 ? "+" : ""}${fmtNum(r.realized_pnl_sol, 4)} SOL`);
    } catch (e: any) { toast("error", e?.message || "Satılamadı"); }
    finally { setBusy(""); }
  }

  return (
    <div>
      {dialog}
      <PageHeader title="Açık Pozisyonlar" icon={<Wallet size={22} />}
        subtitle="Canlı gerçekleşmemiş kâr/zarar — şu an ne kadar artıda/eksideyiz. %50/%100 ile anında (canlı fiyattan) sat." />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Gerçekleşmemiş PnL" tone={totalUnreal >= 0 ? "var(--emerald)" : "var(--rose)"}
          accent={totalUnreal >= 0 ? "var(--emerald)" : "var(--rose)"}
          icon={totalUnreal >= 0 ? <Flame size={18} /> : <Snowflake size={18} />}
          value={haveLive ? <CountUp value={totalUnreal} decimals={4} signed suffix=" ◎" /> : "—"}
          hint={haveLive ? "açık pozisyonların canlı toplamı" : "canlı fiyat bekleniyor"} />
        <StatCard label="Açık Pozisyon" value={sum?.open_positions ?? positions?.length ?? "—"} tone="var(--sky)" icon={<Coins size={18} />} />
        <StatCard label="Açık Risk (maliyet)" value={`${sum?.open_exposure_sol ?? "—"} SOL`} tone="var(--amber)" />
        <StatCard label="Bugünkü Gerçekleşen" value={`${sum?.today_realized_pnl_sol ?? "—"} SOL`} tone="var(--violet)" icon={<TrendingUp size={18} />}
          accent={(sum?.today_realized_pnl_sol ?? 0) >= 0 ? "var(--emerald)" : "var(--rose)"} />
      </div>

      <div className="card mt-4 overflow-x-auto">
        {positions && positions.length > 0 ? (
          <table className="w-full text-sm">
            <thead><tr className="border-b text-left muted" style={{ borderColor: "var(--border)" }}>
              <th className="p-2">Token</th><th className="p-2">Lider</th><th className="p-2 text-right">Maliyet ◎</th>
              <th className="p-2 text-right">Şu anki değer ◎</th><th className="p-2 text-right">Gerçekleşmemiş PnL</th>
              <th className="p-2 text-center">Sat (canlı fiyat)</th>
            </tr></thead>
            <tbody>
              {positions.map((p) => {
                const up = (p.unrealized_pnl_sol ?? 0) >= 0;
                const col = p.unrealized_pnl_sol == null ? "var(--muted)" : up ? "var(--emerald)" : "var(--rose)";
                return (
                  <tr key={p.token_mint} className="table-row border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="p-2">
                      <Link href={`/tokens/${p.token_mint}`} className="clickable font-mono text-xs">{shortAddr(p.token_mint)}</Link>
                      {p.suspicious && <span className="ml-1 badge" title="Değer havuz likiditesini aştığı için sınırlandı (düşük likidite/şüpheli giriş)"
                        style={{ background: "color-mix(in srgb, var(--amber) 18%, transparent)", color: "var(--amber)" }}>⚠ likidite</span>}
                    </td>
                    <td className="p-2"><Link href={`/wallets/${p.wallet_address}`} className="clickable font-mono text-xs">{shortAddr(p.wallet_address)}</Link></td>
                    <td className="p-2 text-right">{fmtNum(p.cost_sol, 4)}</td>
                    <td className="p-2 text-right">{p.current_value_sol == null ? "—" : fmtNum(p.current_value_sol, 4)}</td>
                    <td className="p-2 text-right font-bold" style={{ color: col }}>
                      {p.unrealized_pnl_sol == null ? "—" : (
                        <span className="inline-flex flex-col items-end leading-tight">
                          <span>{up ? "+" : ""}{fmtNum(p.unrealized_pnl_sol, 4)} ◎</span>
                          <span className="text-[11px] font-semibold">{up ? "▲" : "▼"} %{Math.abs(Math.round((p.unrealized_pnl_pct ?? 0) * 100))}</span>
                        </span>
                      )}
                    </td>
                    <td className="p-2">
                      <div className="flex items-center justify-center gap-2">
                        <button className="btn" disabled={!!busy} onClick={() => sell(p, 0.5)}>%50</button>
                        <button className="btn-danger" disabled={!!busy} onClick={() => sell(p, 1)}>%100</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <EmptyState icon={Wallet} title="Açık pozisyon yok" hint="Takip cüzdanları alım yaptıkça pozisyonlar burada canlı PnL ile görünür." />}
      </div>

      <p className="mt-3 text-xs muted">
        Gerçekleşmemiş PnL anlık piyasa fiyatıyla (DexScreener) hesaplanır; fiyat alınamayan token'lerde "—" gösterilir.
        Satışlar paper (simülasyon) ve canlı fiyattan yapılır. Yatırım tavsiyesi değildir.
      </p>
    </div>
  );
}

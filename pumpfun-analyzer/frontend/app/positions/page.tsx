"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { StatCard, Section } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";
import { Empty } from "@/components/States";

export default function Positions() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const { data: positions, mutate } = useSWR<any[]>("/stats/positions", fetcher, { refreshInterval: 12000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 12000 });
  const [price, setPrice] = useState<Record<string, string>>({});

  async function close(mint: string) {
    const p = parseFloat(price[mint] || "0");
    if (!p) { toast("error", "Geçerli bir satış fiyatı (SOL) gir"); return; }
    const ok = await confirm({ title: "Pozisyonu kapat", body: `${shortAddr(mint)} pozisyonu ${p} SOL fiyattan (paper) kapatılacak.`, confirmText: "Kapat" });
    if (!ok) return;
    try { await apiSend(`/stats/positions/${mint}/close?price_sol=${p}`, "POST"); toast("success", "Pozisyon kapatıldı"); await mutate(); }
    catch (e: any) { toast("error", e?.message || "Kapatılamadı"); }
  }

  return (
    <div>
      {dialog}
      <PageHeader title="Açık Pozisyonlar" subtitle="Paper işlemlerden türetilen açık pozisyonlar ve risk göstergeleri" />

      {sum && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <div className="card">
            <div className="text-xs muted">Günlük Harcama</div>
            <div className="mt-1 text-xl font-bold">{sum.today_spent_sol} SOL</div>
          </div>
          <div className="card">
            <div className="text-xs muted">Günlük PnL</div>
            <div className="mt-1 text-xl font-bold" style={{ color: sum.today_realized_pnl_sol >= 0 ? "#10b981" : "#ef4444" }}>{sum.today_realized_pnl_sol} SOL</div>
          </div>
          <StatCard label="Açık Pozisyon" value={sum.open_positions} />
          <StatCard label="Açık Risk" value={`${sum.open_exposure_sol} SOL`} />
        </div>
      )}

      <div className="mt-4">
        <Section title="Pozisyonlar">
          {positions && positions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b text-left">
                  <th className="p-2">Token</th><th className="p-2">Miktar</th><th className="p-2">Maliyet (SOL)</th>
                  <th className="p-2">Gerçekleşmemiş PnL</th><th className="p-2">Manuel Kapat (paper)</th>
                </tr></thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.token_mint} className="table-row border-b last:border-0">
                      <td className="p-2">{shortAddr(p.token_mint)}</td>
                      <td className="p-2">{fmtNum(p.qty, 2)}</td>
                      <td className="p-2">{fmtNum(p.cost_sol, 4)}</td>
                      <td className="p-2" style={{ color: p.unrealized_pnl_sol > 0 ? "#10b981" : p.unrealized_pnl_sol < 0 ? "#ef4444" : undefined }}>
                        {p.unrealized_pnl_sol === null ? "—" : fmtNum(p.unrealized_pnl_sol, 4)}
                      </td>
                      <td className="p-2">
                        <div className="flex items-center gap-2">
                          <input className="input !w-28" placeholder="fiyat SOL" value={price[p.token_mint] || ""} onChange={(e) => setPrice({ ...price, [p.token_mint]: e.target.value })} />
                          <button className="btn" onClick={() => close(p.token_mint)}>Sat</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty label="Açık pozisyon yok" />}
        </Section>
      </div>
    </div>
  );
}

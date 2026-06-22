"use client";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { shortAddr, fmtNum } from "@/lib/api";

export default function Positions() {
  return (
    <div>
      <PageHeader title="Açık Pozisyonlar" subtitle="Aktif (kapanmamış) pozisyonlar ve gerçekleşmemiş PnL" />
      <Fetch<any[]> path="/trading/positions" isEmpty={(d) => d.length === 0} emptyLabel="Açık pozisyon yok" refreshInterval={10000}>
        {(rows) => (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2">Cüzdan</th><th>Token</th><th>Miktar</th><th>Maliyet (SOL)</th><th>Gerçekleşmemiş PnL</th>
              </tr></thead>
              <tbody>
                {rows.map((p, i) => (
                  <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2">{shortAddr(p.wallet_address)}</td>
                    <td>{shortAddr(p.token_mint)}</td>
                    <td>{fmtNum(p.qty_open, 2)}</td>
                    <td>{fmtNum(p.cost_basis_sol, 4)}</td>
                    <td className={p.unrealized_pnl_sol > 0 ? "text-emerald-500" : p.unrealized_pnl_sol < 0 ? "text-red-500" : ""}>{fmtNum(p.unrealized_pnl_sol, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Fetch>
    </div>
  );
}

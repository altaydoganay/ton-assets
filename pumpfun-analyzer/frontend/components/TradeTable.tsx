"use client";
import Link from "next/link";
import { Fetch } from "./Fetch";
import { shortAddr, fmtNum } from "@/lib/api";

export function TradeTable({ path, emptyLabel, live }: { path: string; emptyLabel?: string; live?: boolean }) {
  return (
    <Fetch<any[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel={emptyLabel} refreshInterval={10000}>
      {(rows) => (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
              <th className="pb-2">Zaman</th><th>Cüzdan</th><th>Token</th><th>Yön</th><th>SOL</th>
              <th>PnL (SOL)</th>{live ? <th>Durum</th> : <th>Açık</th>}
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2 muted">{new Date(r.created_at).toLocaleString("tr-TR")}</td>
                  <td><Link href={`/wallets/${r.wallet_address}`} className="clickable">{shortAddr(r.wallet_address)}</Link></td>
                  <td><Link href={`/tokens/${r.token_mint}`} className="clickable">{shortAddr(r.token_mint)}</Link></td>
                  <td><span className={r.side === "buy" ? "text-emerald-500" : "text-red-500"}>{r.side === "buy" ? "Alım" : "Satım"}</span></td>
                  <td>{fmtNum(r.sol_amount, 4)}</td>
                  <td className={r.realized_pnl_sol > 0 ? "text-emerald-500" : r.realized_pnl_sol < 0 ? "text-red-500" : ""}>{fmtNum(r.realized_pnl_sol, 4)}</td>
                  <td className="muted">{live ? r.status : r.is_open ? "Evet" : "Hayır"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Fetch>
  );
}

"use client";
import Link from "next/link";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { shortAddr, fmtNum } from "@/lib/api";

export default function Events() {
  return (
    <div>
      <PageHeader title="Canlı Olay Akışı" subtitle="Zincir üstü tespit edilen gerçek swap işlemleri (transferler ayıklanır)" />
      <Fetch<any[]> path="/events?limit=100" isEmpty={(d) => d.length === 0} emptyLabel="Henüz olay yok" refreshInterval={8000}>
        {(rows) => (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2">Zaman</th><th>Cüzdan</th><th>Token</th><th>Yön</th><th>SOL</th><th>Venue</th><th>Durum</th>
              </tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 muted">{new Date(s.block_time).toLocaleString("tr-TR")}</td>
                    <td><Link href={`/wallets/${s.wallet_address}`} className="clickable">{shortAddr(s.wallet_address)}</Link></td>
                    <td><Link href={`/tokens/${s.token_mint}`} className="clickable">{shortAddr(s.token_mint)}</Link></td>
                    <td><span className={s.side === "buy" ? "text-emerald-500" : "text-red-500"}>{s.side === "buy" ? "Alım" : "Satım"}</span></td>
                    <td>{fmtNum(s.sol_amount, 4)}</td>
                    <td className="muted">{s.venue || "—"}</td>
                    <td className="muted">{s.confirmation}</td>
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

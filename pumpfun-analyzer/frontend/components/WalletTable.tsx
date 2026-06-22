"use client";
import Link from "next/link";
import { Fetch } from "./Fetch";
import { ScoreBadge, StatusBadge, RiskFlags } from "./ScoreBadge";
import { shortAddr } from "@/lib/api";

type Wallet = {
  address: string; label?: string; latest_score?: number; status: string;
  risk_flags?: string[]; confidence?: number; metrics?: Record<string, any>;
};

export function WalletTable({ path, emptyLabel }: { path: string; emptyLabel?: string }) {
  return (
    <Fetch<Wallet[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel={emptyLabel} refreshInterval={20000}>
      {(rows) => (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2">Cüzdan</th>
                <th className="pb-2">Puan</th>
                <th className="pb-2">Durum</th>
                <th className="pb-2">Kapalı Poz.</th>
                <th className="pb-2">Başarı</th>
                <th className="pb-2">Risk Etiketleri</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.address} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2">
                    <Link href={`/wallets/${w.address}`} className="font-medium hover:text-brand">
                      {w.label || shortAddr(w.address)}
                    </Link>
                  </td>
                  <td><ScoreBadge score={w.latest_score} /></td>
                  <td><StatusBadge status={w.status} /></td>
                  <td>{w.metrics?.closed_positions ?? "—"}</td>
                  <td>{w.metrics?.win_rate !== undefined ? `%${Math.round((w.metrics.win_rate as number) * 100)}` : "—"}</td>
                  <td><RiskFlags flags={w.risk_flags} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Fetch>
  );
}

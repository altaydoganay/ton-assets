"use client";
import Link from "next/link";
import { Fetch } from "./Fetch";
import { ScoreBadge, StatusBadge, RiskFlags } from "./ScoreBadge";
import { shortAddr } from "@/lib/api";

type Token = {
  mint: string; name?: string; symbol?: string; stage: string;
  latest_score?: number; status: string; risk_flags?: string[];
};

const STAGE: Record<string, string> = {
  bonding: "Bonding", graduating: "Mezuniyet", graduated: "Mezun", unknown: "Bilinmiyor",
};

export function TokenTable({ path, emptyLabel }: { path: string; emptyLabel?: string }) {
  return (
    <Fetch<Token[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel={emptyLabel} refreshInterval={20000}>
      {(rows) => (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2">Token</th>
                <th className="pb-2">Aşama</th>
                <th className="pb-2">Puan</th>
                <th className="pb-2">Durum</th>
                <th className="pb-2">Riskler</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.mint} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2">
                    <Link href={`/tokens/${t.mint}`} className="font-medium hover:text-brand">
                      {t.symbol || t.name || shortAddr(t.mint)}
                    </Link>
                  </td>
                  <td><span className="badge bg-sky-500/15 text-sky-400">{STAGE[t.stage] || t.stage}</span></td>
                  <td><ScoreBadge score={t.latest_score} /></td>
                  <td><StatusBadge status={t.status} /></td>
                  <td><RiskFlags flags={t.risk_flags} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Fetch>
  );
}

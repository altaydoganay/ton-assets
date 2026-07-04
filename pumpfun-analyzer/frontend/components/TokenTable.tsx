"use client";
import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { Search } from "lucide-react";
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
const FILTERS = [
  { key: "", label: "Tümü" },
  { key: "tracked", label: "Takipte" },
  { key: "analyzed", label: "Analiz edildi" },
  { key: "vetoed", label: "Veto" },
];

export function TokenTable({ path, emptyLabel }: { path: string; emptyLabel?: string }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");

  return (
    <Fetch<Token[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel={emptyLabel} refreshInterval={20000}>
      {(rows) => {
        let r = rows;
        if (filter) r = r.filter((t) => t.status === filter);
        if (q) r = r.filter((t) => (t.mint + (t.symbol || "") + (t.name || "")).toLowerCase().includes(q.toLowerCase()));
        const view = [...r].sort((a, b) => (b.latest_score ?? -1) - (a.latest_score ?? -1));

        return (
          <div className="space-y-3">
            <div className="relative" style={{ maxWidth: 320 }}>
              <Search size={15} className="absolute left-3 top-2.5 muted" />
              <input className="input pl-9" placeholder="Token ara…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="flex flex-wrap gap-2">
              {FILTERS.map((f) => (
                <button key={f.key} className={clsx("chip", filter === f.key && "active")} onClick={() => setFilter(f.key)}>{f.label}</button>
              ))}
            </div>
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-[11px] font-semibold uppercase tracking-wide muted">
                    <th className="p-3">Token</th><th className="p-3">Aşama</th><th className="p-3">Puan</th>
                    <th className="p-3">Durum</th><th className="p-3">Riskler</th>
                  </tr>
                </thead>
                <tbody>
                  {view.map((t) => (
                    <tr key={t.mint} className="table-row border-b last:border-0">
                      <td className="p-3">
                        <Link href={`/tokens/${t.mint}`} className="font-medium hover:text-brand">{t.symbol || t.name || shortAddr(t.mint)}</Link>
                      </td>
                      <td className="p-3"><span className="badge bg-sky-500/15 text-sky-400">{STAGE[t.stage] || t.stage}</span></td>
                      <td className="p-3"><ScoreBadge score={t.latest_score} /></td>
                      <td className="p-3"><StatusBadge status={t.status} /></td>
                      <td className="p-3"><RiskFlags flags={t.risk_flags} /></td>
                    </tr>
                  ))}
                  {view.length === 0 && <tr><td colSpan={5} className="p-8 text-center muted">Eşleşen token yok</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        );
      }}
    </Fetch>
  );
}

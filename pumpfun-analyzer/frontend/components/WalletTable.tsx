"use client";
import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { Search, ArrowUpDown, Download } from "lucide-react";
import { Fetch } from "./Fetch";
import { ScoreBadge, StatusBadge, RiskFlags } from "./ScoreBadge";
import { shortAddr, API_URL } from "@/lib/api";

type Wallet = {
  address: string; label?: string; latest_score?: number; status: string;
  risk_flags?: string[]; metrics?: Record<string, any>;
};

const FILTERS = [
  { key: "", label: "Tümü" },
  { key: "tracked", label: "Takipte" },
  { key: "discovered", label: "Keşfedildi" },
  { key: "analyzed", label: "Analiz edildi" },
  { key: "rejected", label: "Elendi" },
];

export function WalletTable({ path, emptyLabel }: { path: string; emptyLabel?: string }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<"score" | "closed" | "win">("score");

  return (
    <Fetch<Wallet[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel={emptyLabel} refreshInterval={20000}>
      {(rows) => {
        let r = rows;
        if (filter) r = r.filter((w) => w.status === filter);
        if (q) r = r.filter((w) => (w.address + (w.label || "")).toLowerCase().includes(q.toLowerCase()));
        const val = (w: Wallet) =>
          sort === "score" ? (w.latest_score ?? -1)
          : sort === "closed" ? (w.metrics?.closed_positions ?? -1)
          : (w.metrics?.win_rate ?? -1);
        const view = [...r].sort((a, b) => val(b) - val(a));

        return (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1" style={{ minWidth: 220 }}>
                <Search size={15} className="absolute left-3 top-2.5 muted" />
                <input className="input pl-9" placeholder="Adres veya etiket ara…" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <a className="btn" href={`${API_URL}/export/wallets.csv`}><Download size={15} /> CSV</a>
            </div>
            <div className="flex flex-wrap gap-2">
              {FILTERS.map((f) => (
                <button key={f.key} className={clsx("chip", filter === f.key && "active")} onClick={() => setFilter(f.key)}>{f.label}</button>
              ))}
              <div className="ml-auto flex items-center gap-1 text-xs muted">
                <ArrowUpDown size={13} />
                <select className="input !w-auto !py-1 text-xs" value={sort} onChange={(e) => setSort(e.target.value as any)}>
                  <option value="score">Puana göre</option>
                  <option value="closed">Kapalı pozisyona göre</option>
                  <option value="win">Başarıya göre</option>
                </select>
              </div>
            </div>

            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-[11px] font-semibold uppercase tracking-wide muted">
                    <th className="p-3">Cüzdan</th><th className="p-3">Puan</th><th className="p-3">Durum</th>
                    <th className="p-3">Kapalı Poz.</th><th className="p-3">Başarı</th><th className="p-3">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {view.map((w) => (
                    <tr key={w.address} className="table-row border-b last:border-0">
                      <td className="p-3">
                        <Link href={`/wallets/${w.address}`} className="font-medium hover:text-brand">{w.label || shortAddr(w.address)}</Link>
                      </td>
                      <td className="p-3"><ScoreBadge score={w.latest_score} /></td>
                      <td className="p-3"><StatusBadge status={w.status} /></td>
                      <td className="p-3 font-mono tabular-nums">{w.metrics?.closed_positions ?? "—"}</td>
                      <td className="p-3 font-mono tabular-nums">{w.metrics?.win_rate !== undefined ? `%${Math.round((w.metrics.win_rate as number) * 100)}` : "—"}</td>
                      <td className="p-3"><RiskFlags flags={w.risk_flags} /></td>
                    </tr>
                  ))}
                  {view.length === 0 && <tr><td colSpan={6} className="p-8 text-center muted">Eşleşen cüzdan yok</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="text-xs muted">{view.length} / {rows.length} cüzdan</div>
          </div>
        );
      }}
    </Fetch>
  );
}

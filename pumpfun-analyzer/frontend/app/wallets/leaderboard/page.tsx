"use client";
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, shortAddr } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section } from "@/components/ui";
import { Loading } from "@/components/States";
import { Trophy, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

type Row = Record<string, any>;
const COLS: { key: string; label: string; fmt?: (v: any, r?: Row) => string; right?: boolean }[] = [
  { key: "score", label: "Puan", fmt: (v) => (v != null ? Math.round(v).toString() : "—") },
  { key: "win_rate", label: "Başarı", fmt: (v) => (v != null ? `%${Math.round(v * 100)}` : "—") },
  { key: "realized_pnl_sol", label: "Lider PnL (SOL)", right: true, fmt: (v) => (v != null ? Number(v).toFixed(3) : "—") },
  { key: "profit_factor", label: "Profit Factor", fmt: (v) => (v != null ? Number(v).toFixed(2) : "∞/—") },
  { key: "closed_positions", label: "Kapalı İşlem", fmt: (v) => v ?? "—" },
  { key: "token_diversity", label: "Token Çeşit.", fmt: (v) => v ?? "—" },
  { key: "avg_buy_size_sol", label: "Ort. Alım ◎", fmt: (v) => (v != null ? Number(v).toFixed(3) : "—") },
  { key: "history_days", label: "Geçmiş (gün)", fmt: (v) => (v != null ? Math.round(v).toString() : "—") },
];

export default function Leaderboard() {
  const { data } = useSWR<Row[]>("/wallets/leaderboard", fetcher, { refreshInterval: 30000 });
  const [sortKey, setSortKey] = useState("score");
  const [dir, setDir] = useState<1 | -1>(-1);
  if (!data) return <Loading />;

  const rows = [...data].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity, bv = b[sortKey] ?? -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });
  function sortBy(k: string) {
    if (k === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(k); setDir(-1); }
  }
  const SortIco = ({ k }: { k: string }) => k !== sortKey
    ? <ArrowUpDown size={12} className="inline opacity-40" />
    : dir === -1 ? <ArrowDown size={12} className="inline" /> : <ArrowUp size={12} className="inline" />;

  return (
    <div>
      <PageHeader title="🏆 Cüzdan Sıralaması"
        subtitle="Takip ettiğimiz cüzdanların KENDİ al-sat performansı. Başlıklara tıklayıp sırala — kim ne kadar kazanıyor net gör." />
      <Section title={`${rows.length} cüzdan · ${COLS.find((c) => c.key === sortKey)?.label}'a göre sıralı`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="py-2">#</th>
                <th>Cüzdan</th>
                <th>Durum</th>
                {COLS.map((c) => (
                  <th key={c.key} className={`sortable ${c.right ? "text-right" : ""}`} onClick={() => sortBy(c.key)}>
                    {c.label} <SortIco k={c.key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="stagger">
              {rows.map((r, i) => (
                <tr key={r.address} className="table-row border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2">
                    <span className="grid h-5 w-5 place-items-center rounded-md text-[11px] font-bold"
                      style={{ background: i === 0 ? "var(--amber)" : i < 3 ? "color-mix(in srgb, var(--brand) 20%, transparent)" : "transparent",
                               color: i === 0 ? "#1b1300" : "var(--brand)" }}>{i + 1}</span>
                  </td>
                  <td>
                    <Link href={`/wallets/${r.address}`} className="clickable font-mono text-xs">
                      {r.label || shortAddr(r.address)}
                    </Link>
                  </td>
                  <td>
                    <span className="badge" style={{
                      background: r.status === "tracked" ? "color-mix(in srgb, var(--emerald) 16%, transparent)"
                        : r.status === "blocked" ? "color-mix(in srgb, var(--rose) 16%, transparent)" : "var(--bg2)",
                      color: r.status === "tracked" ? "var(--emerald)" : r.status === "blocked" ? "var(--rose)" : "var(--muted)" }}>
                      {r.status === "tracked" ? "Takipte" : r.status === "blocked" ? "Elendi" : r.status}
                    </span>
                  </td>
                  {COLS.map((c) => (
                    <td key={c.key} className={c.right ? "text-right" : ""}
                      style={c.key === "realized_pnl_sol" && r[c.key] != null ? { color: r[c.key] >= 0 ? "var(--emerald)" : "var(--rose)", fontWeight: 600 } : {}}>
                      {c.fmt ? c.fmt(r[c.key], r) : r[c.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

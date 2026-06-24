"use client";
import { useState } from "react";
import clsx from "clsx";
import { Search } from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";

const LEVEL: Record<string, string> = {
  info: "text-sky-400", warning: "text-amber-400", error: "text-red-400", debug: "muted",
};
const LEVELS = [
  { key: "", label: "Tümü" },
  { key: "info", label: "Bilgi" },
  { key: "warning", label: "Uyarı" },
  { key: "error", label: "Hata" },
];

export default function Logs() {
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const path = `/logs?limit=300${level ? `&level=${level}` : ""}`;

  return (
    <div>
      <PageHeader title="Loglar" subtitle="Denetim kayıtları (audit log) — gizli bilgiler maskelenir" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative" style={{ maxWidth: 320 }}>
          <Search size={15} className="absolute left-3 top-2.5 muted" />
          <input className="input pl-9" placeholder="Mesaj/kategori ara…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2">
          {LEVELS.map((l) => (
            <button key={l.key} className={clsx("chip", level === l.key && "active")} onClick={() => setLevel(l.key)}>{l.label}</button>
          ))}
        </div>
      </div>
      <Fetch<any[]> path={path} isEmpty={(d) => d.length === 0} emptyLabel="Henüz log kaydı yok" refreshInterval={12000}>
        {(rows) => {
          const view = q
            ? rows.filter((l) => (l.message + " " + l.category).toLowerCase().includes(q.toLowerCase()))
            : rows;
          return (
            <div className="card font-mono text-xs space-y-1">
              {view.map((l) => (
                <div key={l.id} className="flex flex-wrap gap-2">
                  <span className="muted">{new Date(l.created_at).toLocaleString("tr-TR")}</span>
                  <span className={LEVEL[l.level] || ""}>[{l.level.toUpperCase()}]</span>
                  <span className="muted">{l.category}</span>
                  <span>{l.message}</span>
                </div>
              ))}
              {view.length === 0 && <div className="muted p-4 text-center">Eşleşen kayıt yok</div>}
            </div>
          );
        }}
      </Fetch>
    </div>
  );
}

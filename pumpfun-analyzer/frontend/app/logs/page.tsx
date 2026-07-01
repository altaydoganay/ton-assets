"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { AlertTriangle, Bell, CheckCircle2, Filter, Search, XCircle } from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { PremiumEmpty } from "@/components/PremiumUI";
import { fetcher } from "@/lib/api";

export default function LogsPage() {
  const [level, setLevel] = useState("all");
  const [q, setQ] = useState("");
  const { data } = useSWR<any[]>(`/logs?limit=500${level !== "all" ? `&level=${level}` : ""}`, fetcher, { refreshInterval: 5000 });
  const rows = useMemo(() => (data || []).filter((r) => `${r.message} ${r.category}`.toLowerCase().includes(q.toLowerCase())), [data, q]);
  const levels = ["all", "info", "warning", "error"];
  return (
    <div className="space-y-5">
      <PageHeader title="Karar Günlüğü ve Teknik Loglar" icon={<Bell size={22} />} subtitle="Günlük kullanımda AI/Copy panellerini oku. Bu ekran hata, uyarı ve teknik olayların detay deposudur." />
      <div className="card flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap gap-2">
          {levels.map((x) => <button key={x} className={level === x ? "chip active" : "chip"} onClick={() => setLevel(x)}><Filter size={13} /> {x === "all" ? "Tümü" : x}</button>)}
        </div>
        <div className="relative w-full md:w-96">
          <Search size={15} className="pointer-events-none absolute left-3 top-2.5 muted" />
          <input className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Mesaj veya kategori ara…" />
        </div>
      </div>
      <section className="card">
        {!data ? <PremiumEmpty title="Loglar yükleniyor" text="Backend kayıtları alınıyor." /> : rows.length === 0 ? <PremiumEmpty title="Sonuç yok" text="Seçili filtreye uygun log bulunamadı." /> : (
          <div className="space-y-2 stagger">
            {rows.map((l) => {
              const bad = l.level === "error";
              const warn = l.level === "warning";
              return (
                <div key={l.id} className="decision-log-row">
                  <div className={bad ? "notif-icon bad" : warn ? "notif-icon warn" : "notif-icon ok"}>{bad ? <XCircle size={15} /> : warn ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <b className="text-sm">{l.message}</b>
                      <span className="text-[11px] muted">{new Date(l.created_at).toLocaleString("tr-TR")}</span>
                    </div>
                    <div className="mt-1 text-xs muted">{l.level} · {l.category}</div>
                    {l.context && Object.keys(l.context).length > 0 && <pre className="mt-2 max-h-32 overflow-auto rounded-xl border p-2 text-[11px]" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>{JSON.stringify(l.context, null, 2)}</pre>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

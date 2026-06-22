"use client";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";

const LEVEL: Record<string, string> = {
  info: "text-sky-400", warning: "text-amber-400", error: "text-red-400", debug: "muted",
};

export default function Logs() {
  return (
    <div>
      <PageHeader title="Loglar" subtitle="Denetim kayıtları (audit log) — gizli bilgiler maskelenir" />
      <Fetch<any[]> path="/logs?limit=200" isEmpty={(d) => d.length === 0} emptyLabel="Henüz log kaydı yok" refreshInterval={12000}>
        {(rows) => (
          <div className="card font-mono text-xs space-y-1">
            {rows.map((l) => (
              <div key={l.id} className="flex gap-2">
                <span className="muted">{new Date(l.created_at).toLocaleString("tr-TR")}</span>
                <span className={LEVEL[l.level] || ""}>[{l.level.toUpperCase()}]</span>
                <span className="muted">{l.category}</span>
                <span>{l.message}</span>
              </div>
            ))}
          </div>
        )}
      </Fetch>
    </div>
  );
}

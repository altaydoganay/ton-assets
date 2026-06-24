"use client";
import { CheckCircle2, XCircle } from "lucide-react";

const CRITERIA = [
  { label: "En az 20 kapalı pozisyon", match: "Kapalı pozisyon" },
  { label: "En az 10 farklı token", match: "Farklı token" },
  { label: "En az 30 günlük geçmiş", match: "Geçmiş" },
  { label: "Ücretler sonrası ≥%60 başarı", match: "Başarı oranı" },
  { label: "Medyan tutma süresi ≥30 dk", match: "Medyan tutma" },
  { label: "<10 dk kapanış oranı ≤%35", match: "Kısa süreli" },
  { label: "Tek işlem kârı baskın değil", match: "Tek işlem" },
];

export function EligibilityChecklist({ failures }: { failures?: string[] }) {
  const fails = failures || [];
  return (
    <ul className="space-y-1.5 text-sm">
      {CRITERIA.map((c) => {
        const failed = fails.some((f) => f.includes(c.match));
        return (
          <li key={c.match} className="flex items-center gap-2">
            {failed ? <XCircle size={16} className="text-red-500 shrink-0" /> : <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />}
            <span className={failed ? "text-red-400" : ""}>{c.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

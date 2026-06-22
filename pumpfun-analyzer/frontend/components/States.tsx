"use client";
import { Loader2, Inbox, AlertTriangle } from "lucide-react";

export function Loading({ label = "Yükleniyor…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 muted">
      <Loader2 className="animate-spin" size={18} />
      <span>{label}</span>
    </div>
  );
}

export function Empty({ label = "Henüz veri yok" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 muted">
      <Inbox size={28} />
      <span>{label}</span>
      <span className="text-xs">Veri toplandıkça burada görünecek.</span>
    </div>
  );
}

export function ErrorState({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-red-500">
      <AlertTriangle size={28} />
      <span>Bir hata oluştu</span>
      <span className="text-xs">{message || "Backend'e ulaşılamadı. API ayarlarını kontrol edin."}</span>
    </div>
  );
}

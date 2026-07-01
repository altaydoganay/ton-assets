"use client";
import { useState } from "react";
import { OctagonX, Play, ShieldAlert } from "lucide-react";
import { apiSend } from "@/lib/api";
import { useToast } from "./Toast";

/**
 * Ana ekranda DAİMA görünür acil kill-switch. Ayarlar sayfasına gömülü değil —
 * tek tıkla (onaylı) tüm YENİ alımları durdurur. Aktifken devam et düğmesine döner.
 * Satışlar/çıkışlar motor mantığında zaten serbesttir; bu yalnızca yeni alımları keser.
 */
export function EmergencyStop({ risk, onChange }: { risk: any; onChange: () => void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const stopped = !!risk?.value?.emergency_stop;

  async function stop() {
    setBusy(true);
    try {
      await apiSend("/trading/emergency-stop?close_positions=false", "POST");
      await onChange();
      toast("success", "Acil durdurma etkin — yeni alımlar durduruldu");
    } catch (e: any) {
      toast("error", e?.message || "Durdurulamadı");
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  async function resume() {
    setBusy(true);
    try {
      await apiSend("/trading/resume", "POST");
      await onChange();
      toast("success", "Motor yeniden açıldı");
    } catch (e: any) {
      toast("error", e?.message || "Açılamadı");
    } finally {
      setBusy(false);
    }
  }

  if (stopped) {
    return (
      <button
        className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-bold text-emerald-500"
        style={{ background: "color-mix(in srgb, var(--emerald) 14%, transparent)" }}
        onClick={resume}
        disabled={busy}
        title="Acil durdurmayı kaldır ve motoru aç"
      >
        <Play size={14} /> <span className="hidden sm:inline">Devam Et</span>
      </button>
    );
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="hidden text-[11px] font-semibold text-red-500 sm:inline">Emin misin?</span>
        <button
          className="flex items-center gap-1 rounded-xl bg-red-500 px-2.5 py-1.5 text-xs font-bold text-white"
          onClick={stop}
          disabled={busy}
        >
          <OctagonX size={14} /> Durdur
        </button>
        <button className="btn-ghost text-xs" onClick={() => setConfirming(false)} disabled={busy}>
          Vazgeç
        </button>
      </div>
    );
  }

  return (
    <button
      className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-bold text-red-500"
      style={{ background: "color-mix(in srgb, #ef4444 12%, transparent)" }}
      onClick={() => setConfirming(true)}
      title="Tüm yeni alımları anında durdur"
    >
      <ShieldAlert size={14} /> <span className="hidden sm:inline">Acil Dur</span>
    </button>
  );
}

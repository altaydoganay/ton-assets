"use client";
import { useState } from "react";
import { BrainCircuit, CopyCheck, Layers, RotateCcw } from "lucide-react";
import { apiSend } from "@/lib/api";
import { useToast } from "./Toast";
import { useConfirm } from "./ConfirmDialog";
import { InfoTip } from "./ui";

/**
 * SIFIRLAMA MERKEZİ — tüm sıfırlama işlemlerinin TEK adresi.
 * (Önceden 5 ayrı sayfada farklı kapsamlı butonlar vardı; kafa karıştırıyordu.)
 * Canlı işlemler ve gerçek cüzdan hiçbir seçenekte ETKİLENMEZ.
 */
const SCOPES = [
  { key: "ai", label: "AI Paper", icon: BrainCircuit, tone: "var(--violet)",
    desc: "Yalnız AI_TRADE paper kayıtları/istatistikleri" },
  { key: "copy", label: "Copy Paper", icon: CopyCheck, tone: "var(--emerald)",
    desc: "Yalnız copy (cüzdan takibi) paper kayıtları/istatistikleri" },
  { key: "all", label: "Tümü", icon: Layers, tone: "var(--amber)",
    desc: "AI + Copy tüm paper verisi" },
] as const;

export function ResetCenter({ onDone }: { onDone?: () => void }) {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const [clearPaper, setClearPaper] = useState(true);
  const [busy, setBusy] = useState("");

  async function run(scope: string, label: string) {
    const ok = await confirm({
      title: `${label} sıfırlansın mı?`,
      body: clearPaper
        ? `${label} kapsamındaki paper alım/satım KAYITLARI SİLİNİR ve istatistik dönemi sıfırlanır. Canlı işlemler ve gerçek cüzdan etkilenmez.`
        : `${label} için yalnızca İSTATİSTİK DÖNEMİ sıfırlanır (raporlar bu andan itibaren okunur); kayıt silinmez.`,
      confirmText: clearPaper ? "Kayıtları da sil" : "Dönemi sıfırla",
      danger: clearPaper,
    });
    if (!ok) return;
    setBusy(scope);
    try {
      const res = await apiSend<any>(`/trading/reset-stats?scope=${scope}&clear_paper=${clearPaper}`, "POST");
      toast("success", `${label} sıfırlandı${res?.deleted ? ` (${res.deleted} kayıt silindi)` : ""}`);
      onDone?.();
    } catch (e: any) {
      toast("error", e?.message || "Sıfırlanamadı");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="card" id="reset">
      {dialog}
      <div className="mb-1 flex items-center gap-2">
        <RotateCcw size={16} className="brand" />
        <b>Sıfırlama Merkezi</b>
        <InfoTip title="Sıfırlama Merkezi">
          Tüm sıfırlama işlemlerinin tek adresi. "Kayıtları da sil" açıkken paper işlem
          kayıtları temizlenir; kapalıyken yalnız istatistik dönemi sıfırlanır (kayıt durur,
          raporlar bu andan itibaren okunur). Canlı işlemler ve gerçek cüzdan hiçbir
          seçenekte etkilenmez.
        </InfoTip>
      </div>
      <label className="mb-3 mt-2 flex w-fit cursor-pointer items-center gap-2 text-sm">
        <button className={clearPaper ? "toggle-btn on" : "toggle-btn"} onClick={() => setClearPaper((v) => !v)}>
          {clearPaper ? "Açık" : "Kapalı"}
        </button>
        Paper kayıtlarını da sil (kapalıysa yalnız istatistik dönemi sıfırlanır)
      </label>
      <div className="grid gap-2 sm:grid-cols-3">
        {SCOPES.map((s) => {
          const Icon = s.icon;
          return (
            <button key={s.key} disabled={!!busy} onClick={() => run(s.key, s.label)}
              className="rounded-2xl border p-3 text-left transition hover:opacity-90 disabled:opacity-50"
              style={{ borderColor: `color-mix(in srgb, ${s.tone} 40%, var(--border))` }}>
              <div className="flex items-center gap-2 font-bold" style={{ color: s.tone }}>
                <Icon size={16} /> {s.label}
              </div>
              <div className="mt-1 text-xs muted">{s.desc}</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

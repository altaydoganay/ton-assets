"use client";
import { useState } from "react";
import { Share2, Download, X } from "lucide-react";
import { TradeShareCard, downloadTradeCardPng, cardFromSellRow, type TradeCardData } from "./TradeShareCard";
import { useToast } from "./Toast";

/**
 * Kapanmış işlem satırı için "Paylaş" düğmesi + kart önizleme modalı.
 * Sadece satış (sell) ve realized PnL olan satırlarda görünür.
 */
export function ShareTradeButton({ row, symbol, mode, kind }: {
  row: any; symbol?: string; mode?: "ai" | "copy"; kind?: "paper" | "live";
}) {
  const data = cardFromSellRow(row, { symbol, mode, kind });
  const [open, setOpen] = useState(false);
  if (!data) return null;
  return (
    <>
      <button className="btn-ghost !px-2 !py-1" title="Kâr/zarar kartı oluştur" onClick={() => setOpen(true)}>
        <Share2 size={15} />
      </button>
      {open && <TradeCardModal data={data} onClose={() => setOpen(false)} />}
    </>
  );
}

export function TradeCardModal({ data, onClose }: { data: TradeCardData; onClose: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function dl() {
    setBusy(true);
    try {
      await downloadTradeCardPng(data, `${data.symbol}-${data.pnlPct >= 0 ? "kar" : "zarar"}.png`);
      toast("success", "Kart PNG olarak indirildi");
    } catch (e: any) {
      toast("error", e?.message || "İndirilemedi");
    } finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-2xl rounded-2xl border p-4"
           style={{ background: "var(--card)", borderColor: "var(--border)" }}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-semibold">İşlem Paylaşım Kartı</h3>
          <button className="btn-ghost" onClick={onClose}><X size={18} /></button>
        </div>
        <TradeShareCard data={data} />
        <div className="mt-3 flex justify-end gap-2">
          <button className="btn" onClick={onClose}>Kapat</button>
          <button className="btn-primary" onClick={dl} disabled={busy}>
            <Download size={15} /> {busy ? "Hazırlanıyor…" : "PNG indir"}
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";
import { useState } from "react";
import { mutate } from "swr";
import { apiSend } from "@/lib/api";
import { useToast } from "./Toast";
import { Loader2, Plus } from "lucide-react";

export function AddToken({ refreshPath }: { refreshPath: string }) {
  const [mint, setMint] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function submit() {
    if (!mint.trim()) return;
    setBusy(true);
    try {
      const res: any = await apiSend("/tokens", "POST", { mint: mint.trim() });
      toast("success", `Analiz edildi · Puan: ${res.latest_score?.toFixed?.(0) ?? "—"} · ${res.status}`);
      setMint("");
      mutate(refreshPath);
      mutate("/tokens/tracked");
    } catch (e: any) {
      toast("error", e?.message || "Token analiz edilemedi (Helius/market ayarları?).");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card mb-4">
      <h2 className="mb-2 font-semibold">Token Ekle ve Analiz Et</h2>
      <p className="text-xs muted mb-3">Bir Pump.fun token contract adresi (mint) gir; güvenlik, likidite ve holder analizi yapılır.</p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input className="input" placeholder="Token mint adresi" value={mint} onChange={(e) => setMint(e.target.value)} />
        <button className="btn-primary whitespace-nowrap" onClick={submit} disabled={busy}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {busy ? "Analiz ediliyor…" : "Ekle"}
        </button>
      </div>
    </div>
  );
}

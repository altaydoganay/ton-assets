"use client";
import { useState } from "react";
import { mutate } from "swr";
import { apiSend } from "@/lib/api";
import { Loader2, Plus } from "lucide-react";

export function AddWallet({ refreshPath }: { refreshPath: string }) {
  const [address, setAddress] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit() {
    if (!address.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const res: any = await apiSend("/wallets", "POST", { address: address.trim(), label: label.trim() || null, limit: 100 });
      setMsg({ ok: true, text: `Analiz edildi · Puan: ${res.latest_score?.toFixed?.(0) ?? "—"} · Durum: ${res.status}` });
      setAddress("");
      setLabel("");
      mutate(refreshPath);
      mutate("/wallets/tracked");
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || "Cüzdan analiz edilemedi (RPC/Helius ayarlarını kontrol edin)." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card mb-4">
      <h2 className="mb-2 font-semibold">Cüzdan Ekle ve Analiz Et</h2>
      <p className="text-xs muted mb-3">
        Bir Solana cüzdan adresi girin. Son işlemleri zincirden çekilip puanlanır.
        Helius anahtarı tanımlı olmalı; çok işlemli cüzdanlarda birkaç dakika sürebilir.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input className="input" placeholder="Cüzdan adresi (örn. 9WzD...AWWM)" value={address} onChange={(e) => setAddress(e.target.value)} />
        <input className="input sm:w-48" placeholder="Etiket (opsiyonel)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <button className="btn-primary whitespace-nowrap flex items-center gap-2" onClick={submit} disabled={busy}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {busy ? "Analiz ediliyor…" : "Ekle"}
        </button>
      </div>
      {msg && (
        <div className={`mt-3 text-sm ${msg.ok ? "text-emerald-500" : "text-red-500"}`}>{msg.text}</div>
      )}
    </div>
  );
}

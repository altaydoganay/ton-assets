"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Loading } from "@/components/States";

export default function ApiSettings() {
  const { data: health } = useSWR<any>("/health", fetcher);
  const { data: thr, mutate: mt } = useSWR<{ value: any }>("/settings/thresholds", fetcher);
  const { data: ww, mutate: mw } = useSWR<{ value: any }>("/settings/wallet_weights", fetcher);
  const { data: tw, mutate: mtw } = useSWR<{ value: any }>("/settings/token_weights", fetcher);

  const [thresholds, setThresholds] = useState<any>(null);
  const [walletW, setWalletW] = useState<any>(null);
  const [tokenW, setTokenW] = useState<any>(null);

  useEffect(() => { if (thr?.value) setThresholds(thr.value); }, [thr]);
  useEffect(() => { if (ww?.value) setWalletW(ww.value); }, [ww]);
  useEffect(() => { if (tw?.value) setTokenW(tw.value); }, [tw]);

  if (!thresholds || !walletW || !tokenW) return <Loading />;

  async function saveAll() {
    await apiSend("/settings/thresholds", "PUT", { value: thresholds });
    await apiSend("/settings/wallet_weights", "PUT", { value: walletW });
    await apiSend("/settings/token_weights", "PUT", { value: tokenW });
    await Promise.all([mt(), mw(), mtw()]);
  }

  return (
    <div>
      <PageHeader
        title="API ve RPC Ayarları"
        subtitle="Veri sağlayıcıları .env üzerinden adapter olarak seçilir. Eşikler ve puan ağırlıkları buradan değiştirilebilir."
        action={<button className="btn-primary" onClick={saveAll}>Kaydet</button>}
      />

      <div className="card mb-4">
        <h2 className="font-semibold mb-3">Aktif Sağlayıcılar (.env)</h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><span className="muted">Zincir:</span> <strong>{health?.chain_provider ?? "—"}</strong></div>
          <div><span className="muted">Piyasa:</span> <strong>{health?.market_provider ?? "—"}</strong></div>
        </div>
        <p className="text-xs muted mt-2">
          Helius / Birdeye API anahtarları ve RPC adresleri <code>.env</code> dosyasından
          (<code>CHAIN_PROVIDER</code>, <code>MARKET_PROVIDER</code>, <code>HELIUS_API_KEY</code> …) yönetilir.
        </p>
      </div>

      <div className="card mb-4">
        <h2 className="font-semibold mb-3">Takip Eşikleri</h2>
        <div className="grid grid-cols-2 gap-4">
          <NumberField label="Cüzdan Eşiği" value={thresholds.wallet} onChange={(v) => setThresholds({ ...thresholds, wallet: v })} />
          <NumberField label="Token Eşiği" value={thresholds.token} onChange={(v) => setThresholds({ ...thresholds, token: v })} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <WeightCard title="Cüzdan Puan Ağırlıkları" weights={walletW} onChange={setWalletW} />
        <WeightCard title="Token Puan Ağırlıkları" weights={tokenW} onChange={setTokenW} />
      </div>
    </div>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="text-sm">{label}</label>
      <input className="input mt-1" type="number" step="any" value={value ?? ""} onChange={(e) => onChange(parseFloat(e.target.value))} />
    </div>
  );
}

function WeightCard({ title, weights, onChange }: { title: string; weights: any; onChange: (w: any) => void }) {
  const sum = Object.values(weights).reduce((a: number, b: any) => a + (b as number), 0);
  return (
    <div className="card">
      <h2 className="font-semibold mb-1">{title}</h2>
      <p className={`text-xs mb-3 ${Math.abs(sum - 1) < 0.001 ? "text-emerald-500" : "text-amber-500"}`}>
        Toplam: {sum.toFixed(2)} {Math.abs(sum - 1) < 0.001 ? "✓" : "(1.00 olmalı)"}
      </p>
      <div className="space-y-2">
        {Object.entries(weights).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-2">
            <span className="text-sm">{k}</span>
            <input className="input w-28" type="number" step="0.01" value={v as number}
              onChange={(e) => onChange({ ...weights, [k]: parseFloat(e.target.value) })} />
          </div>
        ))}
      </div>
    </div>
  );
}

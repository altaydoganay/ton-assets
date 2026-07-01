"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Loading } from "@/components/States";
import { InfoTip } from "@/components/ui";

// Ağırlık anahtarları için kısa açıklamalar (?, kullanıcı hangi sinyali
// ayarladığını bilsin). Bilinmeyen anahtar için tip gösterilmez.
const WEIGHT_TIPS: Record<string, string> = {
  copyability: "0.01 SOL ile gecikmeli kopya simülasyonundan gelen kalite — copy kararının EN belirleyici sinyali.",
  performance: "Liderin kendi işlem başarısı ve örneklem kalitesi.",
  consistency: "Sonuçların tutarlılığı; tek büyük vuruşa değil istikrara bakar.",
  risk: "Risk ve maksimum düşüş (drawdown) cezası.",
  organic: "Organik işlem davranışı (bot/wash-trade değil).",
  hold_quality: "Tutma süresi kalitesi — follower için uygunluk.",
  safety: "Rug/copy/insider güvenlik sinyalleri.",
  recency: "Güncellik ve aktiflik (uyuyan cüzdanı düşürür).",
  liquidity: "Havuz likiditesi; düşük likidite yüksek slippage/rug riski.",
  volume: "İşlem hacmi — ilgi ve çıkış kolaylığı göstergesi.",
  holders: "Sahip dağılımı; birkaç cüzdanda yoğunlaşma riskli.",
  safety_flags: "Mint/freeze authority gibi kritik güvenlik bayrakları.",
  age: "Token yaşı — çok yeni tokenlar adil puanlanamaz.",
};

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
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-semibold">Aktif Sağlayıcılar (.env)</h2>
          <InfoTip title="Aktif sağlayıcılar">
            Zincir verisi (işlem geçmişi) ve piyasa verisi (fiyat/likidite) hangi kaynaktan
            çekiliyor. Anahtarlar <code>.env</code>'de yönetilir; sağlık durumu Sistem Sağlığı
            sayfasında canlı izlenir.
          </InfoTip>
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><span className="muted">Zincir:</span> <strong>{health?.chain_provider ?? "—"}</strong></div>
          <div><span className="muted">Piyasa:</span> <strong>{health?.market_provider ?? "—"}</strong></div>
        </div>
        {health?.data_status && (
          <div className="mt-2 text-xs">
            <span className="muted">Veri durumu: </span>
            <strong className={
              health.data_status === "ok" ? "text-emerald-500"
              : health.data_status === "down" ? "text-red-500"
              : health.data_status === "degraded" ? "text-amber-500" : "muted"
            }>{health.data_status}</strong>
            {health.market_data_reliable === false && (
              <span className="text-red-500"> · piyasa verisi güvenilmez (fail-safe alımı durdurabilir)</span>
            )}
          </div>
        )}
        <p className="text-xs muted mt-2">
          Helius / Birdeye API anahtarları ve RPC adresleri <code>.env</code> dosyasından
          (<code>CHAIN_PROVIDER</code>, <code>MARKET_PROVIDER</code>, <code>HELIUS_API_KEY</code> …) yönetilir.
        </p>
      </div>

      <div className="card mb-4">
        <h2 className="font-semibold mb-3">Takip Eşikleri</h2>
        <div className="grid grid-cols-2 gap-4">
          <NumberField label="Cüzdan Eşiği" value={thresholds.wallet} onChange={(v) => setThresholds({ ...thresholds, wallet: v })}
            tip="Bir cüzdanın takip listesine alınması için gereken minimum toplam skor (0-100). Yükseltmek daha seçici yapar, az ama kaliteli cüzdan bırakır." />
          <NumberField label="Token Eşiği" value={thresholds.token} onChange={(v) => setThresholds({ ...thresholds, token: v })}
            tip="Skor-kapılı modda bir tokenın alınabilmesi için gereken minimum token skoru. Taze tokenlar yüksek eşikte az işlem üretir." />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <WeightCard title="Cüzdan Puan Ağırlıkları" weights={walletW} onChange={setWalletW} />
        <WeightCard title="Token Puan Ağırlıkları" weights={tokenW} onChange={setTokenW} />
      </div>
    </div>
  );
}

function NumberField({ label, value, onChange, tip }: { label: string; value: number; onChange: (v: number) => void; tip?: string }) {
  return (
    <div>
      <label className="flex items-center gap-1 text-sm">
        {label}{tip && <InfoTip title={label}>{tip}</InfoTip>}
      </label>
      <input className="input mt-1" type="number" step="any" value={value ?? ""} onChange={(e) => onChange(parseFloat(e.target.value))} />
    </div>
  );
}

function WeightCard({ title, weights, onChange }: { title: string; weights: any; onChange: (w: any) => void }) {
  const sum = Object.values(weights).reduce((a: number, b: any) => a + (b as number), 0);
  return (
    <div className="card">
      <div className="mb-1 flex items-center gap-2">
        <h2 className="font-semibold">{title}</h2>
        <InfoTip title={title}>
          Her sinyalin toplam skora katkı ağırlığı. Toplam 1.00 olmalı; bir ağırlığı artırırsan
          o sinyal karar üzerinde daha baskın olur. Emin değilsen varsayılanları koru.
        </InfoTip>
      </div>
      <p className={`text-xs mb-3 ${Math.abs(sum - 1) < 0.001 ? "text-emerald-500" : "text-amber-500"}`}>
        Toplam: {sum.toFixed(2)} {Math.abs(sum - 1) < 0.001 ? "✓" : "(1.00 olmalı)"}
      </p>
      <div className="space-y-2">
        {Object.entries(weights).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1 text-sm">
              {k}{WEIGHT_TIPS[k] && <InfoTip title={k}>{WEIGHT_TIPS[k]}</InfoTip>}
            </span>
            <input className="input w-28" type="number" step="0.01" value={v as number}
              onChange={(e) => onChange({ ...weights, [k]: parseFloat(e.target.value) })} />
          </div>
        ))}
      </div>
    </div>
  );
}

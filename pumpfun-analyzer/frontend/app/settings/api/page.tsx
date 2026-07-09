"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
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
        title="Skorlama Ayarları"
        subtitle="Takip eşikleri ve cüzdan/token puan ağırlıkları. Veri sağlayıcıları .env'den seçilir; canlı durumu aşağıdaki kartta."
        action={<button className="btn-primary" onClick={saveAll}>Kaydet</button>}
      />
      <SectionTabs group="settings" />

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
        <WeightCard title="Token Puan Ağırlıkları (Copy)" weights={tokenW} onChange={setTokenW} />
      </div>

      <AiHunterCriteria />
    </div>
  );
}

// AI modunun 8 bileşenli avcı token skoru — kod tarafında sabit ağırlıklar
// (score_ai_token). Burada GÖRÜNÜR; eşikler (ana para çıkışı, 10x, stop, migration,
// tape, confirm/scale) "Strateji & Risk" sekmesinden düzenlenir.
const AI_CRITERIA: { key: string; label: string; w: number; src: string }[] = [
  { key: "organic_buyers", label: "Organik erken alıcı kalitesi", w: 20, src: "tape: farklı alıcı, 30sn hız, tek-cüzdan yoğunluğu" },
  { key: "momentum", label: "Momentum hızı ve fiyat davranışı", w: 20, src: "tape: net SOL akışı, al/sat dengesi" },
  { key: "holder_dist", label: "Holder dağılımı", w: 15, src: "top10 / insider / holder sayısı" },
  { key: "dev_behavior", label: "Dev / creator davranışı", w: 15, src: "rugger, rug oranı, dev satışı (tape)" },
  { key: "bot_ratio", label: "Bot / sniper oranı", w: 10, src: "sniper_ratio ya da tek-cüzdan proxy" },
  { key: "sellability", label: "Satılabilirlik ve çıkış kalitesi", w: 10, src: "güvenlik vetosu + gerçek satışlar (tape)" },
  { key: "curve_progress", label: "Bonding curve ilerleme hızı", w: 5, src: "curve_sol / token yaşı (SOL/dk)" },
  { key: "metadata", label: "İsim / logo / narrative", w: 5, src: "isim, sembol, logo varlığı" },
];
const AI_BANDS: { range: string; label: string; tone: string }[] = [
  { range: "0–69", label: "Alma", tone: "var(--rose)" },
  { range: "70–79", label: "Sadece izle", tone: "var(--amber)" },
  { range: "80–87", label: "Scout girişi", tone: "var(--sky)" },
  { range: "88–94", label: "Scout + confirm", tone: "var(--emerald)" },
  { range: "95+", label: "Güçlü scout", tone: "var(--violet)" },
];

function AiHunterCriteria() {
  return (
    <div className="card mt-4">
      <div className="mb-1 flex items-center gap-2">
        <h2 className="font-semibold">AI Avcı Token Skoru (8 bileşen)</h2>
        <InfoTip title="AI avcı skoru">
          AI modu bu 8 bileşenli 100 puanlık skorla karar verir (copy skorundan ayrıdır).
          Ağırlıklar tasarlanmış bir sistemdir ve sabittir; giriş/çıkış EŞİKLERİ
          (ana para çıkışı, 10x, stop, migration, tape kapısı, confirm/scale) “Strateji &amp; Risk”
          sekmesinden düzenlenir. Veri yoksa ilgili bileşen nötr gelir (kör ceza yok).
        </InfoTip>
      </div>
      <p className="text-xs muted mb-3">Toplam 100 · yalnızca AI TRADE modunda geçerli. Bant kararı aşağıda.</p>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {AI_CRITERIA.map((c) => (
          <div key={c.key} className="flex items-center justify-between gap-3 rounded-xl border px-3 py-2" style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--bg2) 45%, transparent)" }}>
            <div className="min-w-0">
              <div className="text-sm font-semibold">{c.label}</div>
              <div className="text-[11px] muted truncate">{c.src}</div>
            </div>
            <span className="font-display tabular shrink-0 rounded-lg px-2 py-1 text-sm font-black" style={{ color: "var(--violet)", background: "color-mix(in srgb, var(--violet) 14%, transparent)" }}>{c.w}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {AI_BANDS.map((b) => (
          <span key={b.range} className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs" style={{ borderColor: `color-mix(in srgb, ${b.tone} 40%, var(--border))` }}>
            <span className="font-mono tabular-nums font-bold" style={{ color: b.tone }}>{b.range}</span>
            <span className="muted">{b.label}</span>
          </span>
        ))}
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

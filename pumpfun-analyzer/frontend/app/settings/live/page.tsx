"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, Callout, StatCard } from "@/components/ui";
import { Loading } from "@/components/States";
import { CheckCircle2, XCircle, Radio, ShieldCheck, Wallet, ArrowRight } from "lucide-react";

export default function LiveSetup() {
  const { data } = useSWR<any>("/setup/live", fetcher, { refreshInterval: 10000 });
  if (!data) return <Loading />;

  const steps = [
    { ok: data.pumpportal_key, label: "PumpPortal Lightning anahtarı (.env: PUMPPORTAL_API_KEY)",
      detail: data.pumpportal_key ? "Tanımlı" : "Eksik — canlı işlem için gerekli" },
    { ok: data.mode === "live", label: "İşlem modu = live",
      detail: `Şu an: ${data.mode}` },
    { ok: data.live_confirmed, label: "Canlı risk onayı (live_confirmed)",
      detail: data.live_confirmed ? "Onaylı" : "Risk Ayarları'ndan onayla" },
    { ok: data.engine_enabled, label: "İşlem motoru açık",
      detail: data.engine_enabled ? "Açık" : "Kapalı" },
  ];

  return (
    <div>
      <PageHeader title="📡 Canlı İşlem Kurulumu"
        subtitle="Gerçek parayla işlemin DÜZENEĞİNİ kur — ama istemeden aktifleşmesin." />

      <div className="mb-4">
        <Callout kind={data.is_live_now ? "warn" : "info"}>
          {data.is_live_now
            ? "⚠️ CANLI İŞLEM ŞU AN AKTİF — gerçek para kullanılıyor."
            : "Şu an PAPER/güvenli moddasın; gerçek para kullanılmıyor. Aşağıdaki adımlar tamamlanıp Risk Ayarları'ndan onaylanana kadar canlı işlem BAŞLAMAZ."}
        </Callout>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="İşlem Sağlayıcı" value={data.trade_provider} tone="var(--violet)" icon={<Radio size={18} />} />
        <StatCard label="Durum" value={data.is_live_now ? "🔴 CANLI" : "🟢 Güvenli"} tone={data.is_live_now ? "var(--rose)" : "var(--emerald)"} />
        <StatCard label="Maks. Pozisyon" value={`${data.max_position_sol ?? "—"} ◎`} tone="var(--sky)" icon={<Wallet size={18} />} />
        <StatCard label="Günlük Limit" value={`${data.max_daily_spend_sol ?? "—"} ◎`} tone="var(--amber)" />
      </div>

      <Section title="Canlıya geçiş kontrol listesi">
        <ul className="space-y-2">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center gap-3 rounded-xl border p-3" style={{ borderColor: "var(--border)" }}>
              {s.ok ? <CheckCircle2 size={20} className="text-emerald-500 shrink-0" /> : <XCircle size={20} className="text-red-500 shrink-0" />}
              <div className="flex-1">
                <div className="font-medium">{s.label}</div>
                <div className="text-xs muted">{s.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      </Section>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Nasıl kurulur (adım adım)">
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li><b>Ayrı, düşük bakiyeli bir cüzdan</b> hazırla — ana cüzdanını ASLA kullanma.</li>
            <li><a className="clickable" href="https://pumpportal.fun" target="_blank" rel="noreferrer">pumpportal.fun</a>'da Lightning cüzdanı oluştur, içine <b>az miktar SOL</b> gönder.</li>
            <li>Aldığın <b>Lightning API anahtarını</b> sunucudaki <code>.env</code> dosyasına yaz:
              <div className="mt-1 rounded-lg p-2 font-mono text-xs" style={{ background: "var(--bg2)" }}>PUMPPORTAL_API_KEY=...</div>
              ve <code>docker compose up -d --build</code> ile yeniden başlat.</li>
            <li>Hazır olunca <Link href="/settings/risk" className="clickable">Risk Ayarları</Link>'na gel: <b>Mod = live</b> yap, kaydet → çıkan onayı kabul et. İşlem Motoru = Açık.</li>
            <li>Önce <b>küçük limitlerle</b> (Maks. Pozisyon, Günlük Harcama düşük) başla; birkaç işlem izle.</li>
          </ol>
        </Section>

        <Section title="Güvenlik">
          <ul className="space-y-2 text-sm">
            <li className="flex gap-2"><ShieldCheck size={16} className="brand mt-0.5 shrink-0" /> Özel anahtarın PumpPortal tarafında kalır; bizim DB/loglarımıza <b>asla</b> yazılmaz.</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="brand mt-0.5 shrink-0" /> Her işlem öncesi token güvenliği + satılabilirlik son kez kontrol edilir.</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="brand mt-0.5 shrink-0" /> Slippage tavanı tepeden alımı önler; <b>Acil Durdurma</b> her an tüm işlemleri keser.</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="brand mt-0.5 shrink-0" /> Kârlılık garantisi yoktur; yatırım tavsiyesi değildir.</li>
          </ul>
          <div className="mt-3"><Link href="/settings/risk" className="btn-primary">Risk Ayarları'na git <ArrowRight size={14} /></Link></div>
        </Section>
      </div>
    </div>
  );
}

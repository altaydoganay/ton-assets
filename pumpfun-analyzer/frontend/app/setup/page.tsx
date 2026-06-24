"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, Callout } from "@/components/ui";
import { CheckCircle2, XCircle, ArrowRight } from "lucide-react";
import { Loading } from "@/components/States";

export default function Setup() {
  const { data } = useSWR<any>("/setup", fetcher, { refreshInterval: 15000 });
  if (!data) return <Loading />;

  const fixes: Record<string, { label: string; href: string }> = {
    helius: { label: "API ve RPC Ayarları", href: "/settings/api" },
    listener: { label: "Sistem Sağlığı", href: "/health" },
    telegram: { label: "API ve RPC Ayarları", href: "/settings/api" },
    trading: { label: "Risk Ayarları", href: "/settings/risk" },
  };

  return (
    <div>
      <PageHeader
        title="Kurulum & Sağlık"
        subtitle="Sistemin doğru çalışması için gereken her şey tek ekranda"
      />

      <div className="mb-4">
        <Callout kind={data.healthy ? "info" : "warn"}>
          {data.healthy
            ? `Sistem çalışıyor — ${data.ok_count}/${data.total} kontrol başarılı. Keşif ve analiz aktif.`
            : "Bazı kritik kontroller başarısız. Aşağıdaki kırmızı maddeleri düzeltmeden keşif/analiz çalışmayabilir."}
        </Callout>
      </div>

      <Section title="Kontrol Listesi">
        <ul className="space-y-2">
          {data.checks.map((c: any) => (
            <li key={c.key} className="flex items-center justify-between rounded-xl border p-3" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-center gap-3">
                {c.ok ? <CheckCircle2 size={20} className="text-emerald-500" /> : <XCircle size={20} className="text-red-500" />}
                <div>
                  <div className="font-medium">{c.label}</div>
                  <div className="text-xs muted">{c.detail}</div>
                </div>
              </div>
              {!c.ok && fixes[c.key] && (
                <Link href={fixes[c.key].href} className="btn-ghost">{fixes[c.key].label} <ArrowRight size={13} /></Link>
              )}
            </li>
          ))}
        </ul>
      </Section>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <InfoCard label="İşlem Modu" value={data.trading_mode === "live" ? "🔴 Canlı" : data.trading_mode === "paper" ? "🟢 Paper" : "🔵 Bildirim"} />
        <InfoCard label="İşlem Motoru" value={data.engine_enabled ? "Açık" : "Kapalı"} />
        <InfoCard label="Keşif Hızı" value={`${data.discovery_max_lookups_per_min}/dk`} hint={data.discovery_enabled ? "Keşif açık" : "Keşif kapalı"} />
      </div>

      <div className="mt-4">
        <Callout kind="warn">
          <b>Güvenlik:</b> Canlı işleme geçmeden önce <b>ayrı ve düşük bakiyeli</b> bir cüzdan kullan. Önce Paper modunda
          birkaç gün gözlemlemeni öneririz. Kârlılık garantisi yoktur.
        </Callout>
      </div>
    </div>
  );
}

function InfoCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="text-xs muted">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {hint && <div className="text-xs muted">{hint}</div>}
    </div>
  );
}

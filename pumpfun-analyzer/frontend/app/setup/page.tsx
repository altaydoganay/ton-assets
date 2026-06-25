"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, Callout } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { CheckCircle2, XCircle, ArrowRight } from "lucide-react";
import { Loading } from "@/components/States";

export default function Setup() {
  const { data, mutate } = useSWR<any>("/setup", fetcher, { refreshInterval: 15000 });
  const toast = useToast();
  if (!data) return <Loading />;

  async function toggleDiscovery(enabled: boolean) {
    try {
      await apiSend(`/setup/discovery?enabled=${enabled}`, "POST");
      await mutate();
      toast("success", enabled ? "Keşif açıldı" : "Keşif kapatıldı — kredi korunuyor");
    } catch (e: any) { toast("error", e?.message || "İşlem başarısız"); }
  }

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

      <Section title="Keşif Akışı (Helius kredi kontrolü)">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm">
            <div className="font-medium">
              Keşif (pump.fun canlı akışı): {data.discovery_enabled ? "🟢 Açık" : "⚪ Kapalı"}
            </div>
            <div className="muted text-xs mt-1 max-w-2xl">
              Keşif, yeni cüzdan bulmak için pump.fun'ın <b>tüm canlı akışına</b> abone olur. Helius bunu
              <b> MB başına ücretlendirir</b> — kredinin EN BÜYÜK kalemidir. Yeterince aday (backlog) bulduysan
              <b> kapat</b>: kredi düşer, analiz mevcut adaylar üzerinde devam eder, işlemler (poll izleyici) çalışmaya devam eder.
            </div>
          </div>
          <button
            className={data.discovery_enabled ? "btn-danger whitespace-nowrap" : "btn-primary whitespace-nowrap"}
            onClick={() => toggleDiscovery(!data.discovery_enabled)}
          >
            {data.discovery_enabled ? "Keşfi Kapat (kredi koru)" : "Keşfi Aç"}
          </button>
        </div>
      </Section>

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

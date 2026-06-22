"use client";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";

function Row({ label, ok, text }: { label: string; ok?: boolean | null; text?: string }) {
  return (
    <div className="flex items-center justify-between border-b py-3 last:border-0" style={{ borderColor: "var(--border)" }}>
      <span>{label}</span>
      {text ? <span className="font-medium">{text}</span> : (
        <span className={ok ? "text-emerald-500" : "text-red-500"}>{ok ? "✅ Açık" : "❌ Kapalı"}</span>
      )}
    </div>
  );
}

export default function Health() {
  return (
    <div>
      <PageHeader title="Sistem Sağlığı" subtitle="Servis durumu ve aktif sağlayıcı yapılandırması" />
      <Fetch<any> path="/health" refreshInterval={10000}>
        {(h) => (
          <div className="card max-w-xl">
            <Row label="Genel Durum" text={h.status === "ok" ? "✅ Sağlıklı" : "⚠️ Kısıtlı"} />
            <Row label="Veritabanı (PostgreSQL)" ok={h.database} />
            <Row label="Redis" ok={h.redis} />
            <Row label="Zincir Sağlayıcı" text={h.chain_provider} />
            <Row label="Piyasa Sağlayıcı" text={h.market_provider} />
            <Row label="İşlem Modu" text={h.trading_mode} />
            <Row label="Telegram" ok={h.telegram_enabled} />
            <Row label="Sürüm" text={h.version} />
          </div>
        )}
      </Fetch>
    </div>
  );
}

"use client";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { InfoTip } from "@/components/ui";

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

const STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: "Sağlıklı", cls: "text-emerald-500 bg-emerald-500/10" },
  degraded: { label: "Kısıtlı", cls: "text-amber-500 bg-amber-500/10" },
  down: { label: "Down", cls: "text-red-500 bg-red-500/10" },
  unknown: { label: "Bilinmiyor", cls: "text-slate-400 bg-slate-500/10" },
};

function StatusPill({ status }: { status: string }) {
  const m = STATUS_META[status] || STATUS_META.unknown;
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${m.cls}`}>{m.label}</span>;
}

function ago(ts?: number | null): string {
  if (!ts) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}sn önce`;
  if (s < 3600) return `${Math.floor(s / 60)}dk önce`;
  return `${Math.floor(s / 3600)}sa önce`;
}

function ProviderCard({ p }: { p: any }) {
  const fail = p.recent_fail_ratio == null ? null : Math.round(p.recent_fail_ratio * 100);
  return (
    <div className="border-b py-3 last:border-0" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{p.name}</span>
          <span className="text-xs opacity-60">{p.kind === "market" ? "piyasa" : "zincir"}</span>
        </div>
        <StatusPill status={p.status} />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs opacity-70">
        <span>{p.ok}/{p.total} başarılı</span>
        {fail != null && <span>son pencere hata: %{fail}</span>}
        {p.avg_latency_ms != null && <span>ort. {p.avg_latency_ms}ms</span>}
        <span>son ok: {ago(p.last_ok_ts)}</span>
        {p.consecutive_failures > 0 && (
          <span className="text-red-500">üst üste {p.consecutive_failures} hata</span>
        )}
      </div>
      {p.status !== "ok" && p.last_error && (
        <div className="mt-1 truncate text-xs text-red-400" title={p.last_error}>⚠ {p.last_error}</div>
      )}
    </div>
  );
}

export default function Health() {
  return (
    <div>
      <PageHeader title="Sistem Sağlığı" subtitle="Servis durumu, veri sağlayıcı sağlığı ve aktif yapılandırma" />
      <Fetch<any> path="/health" refreshInterval={10000}>
        {(h) => (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card">
              <Row label="Genel Durum" text={h.status === "ok" ? "✅ Sağlıklı" : "⚠️ Kısıtlı"} />
              <Row label="Veritabanı (PostgreSQL)" ok={h.database} />
              <Row label="Redis" ok={h.redis} />
              <Row label="Zincir Sağlayıcı" text={h.chain_provider} />
              <Row label="Piyasa Sağlayıcı" text={h.market_provider} />
              <Row label="İşlem Modu" text={h.trading_mode} />
              <Row label="Telegram" ok={h.telegram_enabled} />
              <Row label="Sürüm" text={h.version} />
            </div>

            <div className="card">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold">Veri Sağlayıcı Sağlığı</h3>
                  <InfoTip title="Veri sağlayıcı sağlığı">
                    Her piyasa/zincir sağlayıcı çağrısının başarısı burada izlenir. Bir sağlayıcı
                    "down" olduğunda panel uyarır; hiçbir piyasa sağlayıcı ayakta değilse fiyat
                    verisi güvenilmez sayılır ve fail-safe kapıları yeni alımı engeller.
                  </InfoTip>
                </div>
                <StatusPill status={h.data_status || "unknown"} />
              </div>

              {h.market_data_reliable === false && (
                <div className="mb-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
                  ⚠ Hiçbir piyasa sağlayıcı ayakta değil — fiyat verisi güvenilmez. Yeni alımlar
                  fail-safe olarak duraklatılabilir.
                </div>
              )}

              {(!h.providers || h.providers.length === 0) ? (
                <div className="py-6 text-center text-sm opacity-60">
                  Henüz sağlayıcı çağrısı kaydedilmedi. Listener/analiz çalışınca burada görünür.
                </div>
              ) : (
                h.providers.map((p: any) => <ProviderCard key={`${p.kind}:${p.name}`} p={p} />)
              )}
            </div>
          </div>
        )}
      </Fetch>
    </div>
  );
}

"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { ScoreBadge, StatusBadge } from "@/components/ScoreBadge";
import Link from "next/link";

type Wallet = { address: string; label?: string; latest_score?: number; status: string };
type Health = { status: string; database: boolean; redis: boolean | null; trading_mode: string; telegram_enabled: boolean };

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card">
      <div className="text-xs muted">{label}</div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
      {hint && <div className="text-xs muted mt-1">{hint}</div>}
    </div>
  );
}

export default function Overview() {
  const { data: tracked } = useSWR<Wallet[]>("/wallets/tracked", fetcher);
  const { data: trackedTokens } = useSWR<any[]>("/tokens/tracked", fetcher);
  const { data: alerts } = useSWR<any[]>("/alerts?limit=5", fetcher);
  const { data: health } = useSWR<Health>("/health", fetcher, { refreshInterval: 15000 });

  return (
    <div>
      <PageHeader
        title="Genel Bakış"
        subtitle="Sistem durumu, takip edilen cüzdan/token özeti ve son bildirimler"
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Takip Edilen Cüzdan" value={tracked?.length ?? "—"} />
        <Stat label="Takip Edilen Token" value={trackedTokens?.length ?? "—"} />
        <Stat
          label="İşlem Modu"
          value={health?.trading_mode === "live" ? "Canlı" : health?.trading_mode === "paper" ? "Paper" : health?.trading_mode === "alerts_only" ? "Bildirim" : "—"}
        />
        <Stat
          label="Sistem"
          value={health ? (health.status === "ok" ? "✅ Sağlıklı" : "⚠️ Kısıtlı") : "—"}
          hint={health ? `DB: ${health.database ? "açık" : "kapalı"} · Redis: ${health.redis ? "açık" : "kapalı"}` : undefined}
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-semibold">En İyi Takip Edilen Cüzdanlar</h2>
          <Fetch<Wallet[]> path="/wallets/tracked" isEmpty={(d) => d.length === 0} emptyLabel="Henüz takip edilen cüzdan yok">
            {(data) => (
              <ul className="space-y-2">
                {data.slice(0, 6).map((w) => (
                  <li key={w.address} className="flex items-center justify-between">
                    <Link href={`/wallets/${w.address}`} className="text-sm hover:text-brand">
                      {w.label || w.address.slice(0, 10) + "…"}
                    </Link>
                    <ScoreBadge score={w.latest_score} />
                  </li>
                ))}
              </ul>
            )}
          </Fetch>
        </div>

        <div className="card">
          <h2 className="mb-3 font-semibold">Son Bildirimler</h2>
          <Fetch<any[]> path="/alerts?limit=6" isEmpty={(d) => d.length === 0} emptyLabel="Henüz bildirim yok">
            {(data) => (
              <ul className="space-y-2">
                {data.map((a) => (
                  <li key={a.id} className="flex items-center justify-between text-sm">
                    <span>{a.wallet_address.slice(0, 6)}… → {a.token_mint.slice(0, 6)}…</span>
                    <span className="muted text-xs">{a.sent ? "Gönderildi" : "Beklemede"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Fetch>
        </div>
      </div>

      <p className="mt-6 text-xs muted">
        Bu panel veri yeterliliği ve güven seviyesini her analizde gösterir. Eksik veya
        doğrulanmamış veriler kesin bilgi gibi sunulmaz.
      </p>
    </div>
  );
}

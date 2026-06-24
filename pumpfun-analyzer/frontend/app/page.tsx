"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, shortAddr } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { StatCard, Section } from "@/components/ui";
import { ScoreBadge } from "@/components/ScoreBadge";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

const tip = { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 };

export default function Overview() {
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: ts } = useSWR<any[]>("/stats/timeseries?days=14", fetcher, { refreshInterval: 30000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 30000 });
  const { data: tracked } = useSWR<any[]>("/wallets/tracked", fetcher, { refreshInterval: 20000 });
  const { data: alerts } = useSWR<any[]>("/alerts?limit=6", fetcher, { refreshInterval: 15000 });

  return (
    <div>
      <PageHeader title="Genel Bakış" subtitle="Keşif hunisi, performans ve son aktivite" />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Takip Edilen Cüzdan" value={ov?.wallets?.tracked ?? "—"} accent="#2dd4bf"
          hint={ov ? `${ov.wallets.total} toplam · ${ov.wallets.discovered} keşfedildi` : undefined} />
        <StatCard label="Takip Edilen Token" value={ov?.tokens?.tracked ?? "—"} />
        <StatCard label="Bugünkü Bildirim" value={ov?.alerts?.today ?? "—"} hint={ov ? `${ov.alerts.total} toplam` : undefined} />
        <StatCard label="Paper PnL (SOL)" value={ov ? ov.pnl.paper_sol.toFixed(3) : "—"}
          accent={ov && ov.pnl.paper_sol >= 0 ? "#10b981" : "#ef4444"} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Section title="Keşif Hunisi (14 gün)">
          {ts && ts.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={ts}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                <YAxis stroke="var(--muted)" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={tip} />
                <Bar dataKey="discovered" name="Keşfedilen" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                <Bar dataKey="tracked" name="Takibe alınan" fill="#2dd4bf" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <Empty />}
          <div className="mt-2 flex gap-4 text-xs muted">
            <span><b className="text-sky-400">{ov?.funnel?.discovered_today ?? 0}</b> bugün keşfedildi</span>
            <span><b className="brand">{ov?.funnel?.analyzed_today ?? 0}</b> bugün analiz edildi</span>
          </div>
        </Section>

        <Section title="Paper PnL Eğrisi">
          {perf?.curve?.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={perf.curve}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0} />
                </linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="t" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                <YAxis stroke="var(--muted)" fontSize={11} />
                <Tooltip contentStyle={tip} />
                <Area type="monotone" dataKey="pnl" stroke="#2dd4bf" strokeWidth={2} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <Empty label="Henüz kapanmış paper işlem yok" />}
          {perf && <div className="mt-2 text-xs muted">Başarı: <b>%{Math.round((perf.win_rate || 0) * 100)}</b> · {perf.closed_trades} kapanmış işlem</div>}
        </Section>

        <Section title="En İyi Takip Edilen Cüzdanlar">
          {tracked?.length ? (
            <ul className="space-y-2">
              {tracked.slice(0, 7).map((w) => (
                <li key={w.address} className="flex items-center justify-between">
                  <Link href={`/wallets/${w.address}`} className="text-sm hover:text-brand">{w.label || shortAddr(w.address)}</Link>
                  <ScoreBadge score={w.latest_score} />
                </li>
              ))}
            </ul>
          ) : <Empty label="Henüz takip edilen cüzdan yok" />}
        </Section>
      </div>

      <div className="mt-4">
        <Section title="Son Bildirimler" action={<Link href="/alerts" className="btn-ghost">Tümü →</Link>}>
          {alerts?.length ? (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {alerts.map((a) => (
                <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                  <span>{shortAddr(a.wallet_address)} → <Link href={`/tokens/${a.token_mint}`} className="hover:text-brand">{shortAddr(a.token_mint)}</Link></span>
                  <span className="muted text-xs">{a.sent ? "Gönderildi" : "Beklemede"}</span>
                </li>
              ))}
            </ul>
          ) : <Empty label="Henüz bildirim yok" />}
        </Section>
      </div>

      <p className="mt-6 text-xs muted">Bu panel veri yeterliliği ve güven seviyesini her analizde gösterir. Eksik veya doğrulanmamış veriler kesin bilgi gibi sunulmaz.</p>
    </div>
  );
}

function Empty({ label = "Veri toplandıkça burada görünecek" }: { label?: string }) {
  return <div className="flex h-[200px] items-center justify-center text-sm muted">{label}</div>;
}

"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, shortAddr } from "@/lib/api";
import { StatCard, Section } from "@/components/ui";
import { ScoreBadge } from "@/components/ScoreBadge";
import { MoodHero } from "@/components/MoodHero";
import { Wallet, Coins, Bell, TrendingUp, ArrowRight, Activity } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

const tip = { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 };

export default function Overview() {
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: ts } = useSWR<any[]>("/stats/timeseries?days=14", fetcher, { refreshInterval: 30000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 30000 });
  const { data: tracked } = useSWR<any[]>("/wallets/tracked", fetcher, { refreshInterval: 20000 });
  const { data: alerts } = useSWR<any[]>("/alerts?limit=6", fetcher, { refreshInterval: 15000 });

  const pnl = ov ? ov.pnl.paper_sol : 0;
  const pnlUp = pnl >= 0;

  return (
    <div>
      <MoodHero />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Takip Edilen Cüzdan" value={ov?.wallets?.tracked ?? "—"} tone="var(--brand)" icon={<Wallet size={18} />}
          hint={ov ? `${ov.wallets.total} toplam · ${ov.wallets.discovered} keşfedildi` : undefined} />
        <StatCard label="Takip Edilen Token" value={ov?.tokens?.tracked ?? "—"} tone="var(--violet)" icon={<Coins size={18} />} />
        <StatCard label="Bugünkü Bildirim" value={ov?.alerts?.today ?? "—"} tone="var(--amber)" icon={<Bell size={18} />}
          hint={ov ? `${ov.alerts.total} toplam` : undefined} />
        <StatCard label="Paper PnL (SOL)" value={ov ? pnl.toFixed(3) : "—"} tone={pnlUp ? "var(--emerald)" : "var(--rose)"}
          icon={<TrendingUp size={18} />} accent={pnlUp ? "var(--emerald)" : "var(--rose)"} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Section title="🔭 Keşif Hunisi (14 gün)">
          {ts && ts.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={ts}>
                <defs>
                  <linearGradient id="bDisc" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" /><stop offset="100%" stopColor="#0ea5e9" stopOpacity={0.6} />
                  </linearGradient>
                  <linearGradient id="bTrack" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2dd4bf" /><stop offset="100%" stopColor="#10b981" stopOpacity={0.7} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                <YAxis stroke="var(--muted)" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={tip} cursor={{ fill: "rgba(125,125,125,0.06)" }} />
                <Bar dataKey="discovered" name="Keşfedilen" fill="url(#bDisc)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="tracked" name="Takibe alınan" fill="url(#bTrack)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <Empty />}
          <div className="mt-2 flex gap-4 text-xs muted">
            <span><b style={{ color: "var(--sky)" }}>{ov?.funnel?.discovered_today ?? 0}</b> bugün keşfedildi</span>
            <span><b className="brand">{ov?.funnel?.analyzed_today ?? 0}</b> bugün analiz edildi</span>
          </div>
        </Section>

        <Section title="📈 Paper PnL Eğrisi">
          {perf?.curve?.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={perf.curve}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={pnlUp ? "#10b981" : "#ef4444"} stopOpacity={0.45} />
                  <stop offset="100%" stopColor={pnlUp ? "#10b981" : "#ef4444"} stopOpacity={0} />
                </linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="t" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                <YAxis stroke="var(--muted)" fontSize={11} />
                <Tooltip contentStyle={tip} />
                <Area type="monotone" dataKey="pnl" stroke={pnlUp ? "#10b981" : "#ef4444"} strokeWidth={2.5} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <Empty label="Henüz kapanmış paper işlem yok" />}
          {perf && <div className="mt-2 text-xs muted">Başarı: <b style={{ color: "var(--emerald)" }}>%{Math.round((perf.win_rate || 0) * 100)}</b> · {perf.closed_trades} kapanmış işlem</div>}
        </Section>

        <Section title="🏆 En İyi Takip Edilen Cüzdanlar" action={<Link href="/wallets/tracked" className="btn-ghost">Tümü <ArrowRight size={12} /></Link>}>
          {tracked?.length ? (
            <ul className="space-y-1.5">
              {tracked.slice(0, 7).map((w, i) => (
                <li key={w.address} className="flex items-center justify-between rounded-lg px-2 py-1.5 table-row">
                  <span className="flex items-center gap-2 text-sm">
                    <span className="grid h-5 w-5 place-items-center rounded-md text-[11px] font-bold"
                      style={{ background: i === 0 ? "var(--amber)" : "color-mix(in srgb, var(--brand) 18%, transparent)", color: i === 0 ? "#1b1300" : "var(--brand)" }}>
                      {i + 1}
                    </span>
                    <Link href={`/wallets/${w.address}`} className="hover:text-brand">{w.label || shortAddr(w.address)}</Link>
                  </span>
                  <ScoreBadge score={w.latest_score} />
                </li>
              ))}
            </ul>
          ) : <Empty label="Henüz takip edilen cüzdan yok" />}
        </Section>
      </div>

      <div className="mt-4">
        <Section title="🔔 Son Bildirimler" action={<Link href="/alerts" className="btn-ghost">Tümü <ArrowRight size={12} /></Link>}>
          {alerts?.length ? (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {alerts.map((a) => (
                <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <Activity size={14} style={{ color: "var(--brand)" }} />
                    {shortAddr(a.wallet_address)} → <Link href={`/tokens/${a.token_mint}`} className="hover:text-brand">{shortAddr(a.token_mint)}</Link>
                  </span>
                  <span className="badge" style={{ background: a.sent ? "color-mix(in srgb, var(--emerald) 18%, transparent)" : "color-mix(in srgb, var(--amber) 18%, transparent)", color: a.sent ? "var(--emerald)" : "var(--amber)" }}>
                    {a.sent ? "Gönderildi" : "Beklemede"}
                  </span>
                </li>
              ))}
            </ul>
          ) : <Empty label="Henüz bildirim yok" />}
        </Section>
      </div>

      <p className="mt-6 text-xs muted">Bu panel veri yeterliliği ve güven seviyesini her analizde gösterir. Eksik veya doğrulanmamış veriler kesin bilgi gibi sunulmaz. Yatırım tavsiyesi değildir.</p>
    </div>
  );
}

function Empty({ label = "Veri toplandıkça burada görünecek" }: { label?: string }) {
  return <div className="flex h-[200px] items-center justify-center text-sm muted">{label}</div>;
}

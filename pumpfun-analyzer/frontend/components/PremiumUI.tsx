"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  Activity, AlertTriangle, Bell, BrainCircuit, CheckCircle2, ChevronRight,
  CircleDollarSign, Command, CopyCheck, ExternalLink, Eye, Gauge, HeartPulse,
  HelpCircle, History, Keyboard, LineChart as LineChartIcon, Loader2, Moon,
  Radio, Rocket, Search, Server, ShieldCheck, Sparkles, Target, TimerReset,
  Wallet, X, XCircle, Zap,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar,
  PieChart, Pie, Cell, Tooltip, XAxis, YAxis,
} from "recharts";
import { apiSend, fetcher, fmtNum, shortAddr } from "@/lib/api";
import { useToast } from "@/components/Toast";

type Mode = "ai" | "copy";

type ChartPoint = Record<string, any>;

const MODE_LINKS: Record<Mode, { href: string; label: string; hint: string; icon: any }[]> = {
  ai: [
    { href: "/overview", label: "Mod Seçimi", hint: "AI / Copy geçiş ekranı", icon: Rocket },
    { href: "/ai", label: "AI Decision Center", hint: "AI kararları, huni, paper sonuçları", icon: BrainCircuit },
    { href: "/tokens", label: "Token Analizi", hint: "Token skorları ve risk sinyalleri", icon: Target },
    { href: "/positions", label: "Açık Pozisyonlar", hint: "Paper/live pozisyon ve gerçek cüzdan", icon: Wallet },
    { href: "/history", label: "İşlem Geçmişi", hint: "Kapanan işlemler", icon: History },
    { href: "/settings/risk", label: "AI Risk Ayarları", hint: "AI profil ve çıkış kuralları", icon: Gauge },
    { href: "/health", label: "Sistem Sağlığı", hint: "Listener, API, worker durumu", icon: HeartPulse },
  ],
  copy: [
    { href: "/overview", label: "Mod Seçimi", hint: "AI / Copy geçiş ekranı", icon: Rocket },
    { href: "/copy", label: "Copy Trade Paneli", hint: "Copy kararları ve performansı", icon: CopyCheck },
    { href: "/wallets/leaderboard", label: "Cüzdan Sıralaması", hint: "Elite rebuild ve copyability", icon: ShieldCheck },
    { href: "/wallets/tracked", label: "Takip Edilenler", hint: "Canlı/copy izinli cüzdanlar", icon: Eye },
    { href: "/positions", label: "Açık Pozisyonlar", hint: "Açık copy pozisyonları", icon: Wallet },
    { href: "/performance", label: "Copy Performansı", hint: "Paper copy PnL ve win rate", icon: LineChartIcon },
    { href: "/health", label: "Sistem Sağlığı", hint: "Listener, API, worker durumu", icon: HeartPulse },
  ],
};

export function PremiumBackdrop() {
  return (
    <div className="premium-backdrop" aria-hidden>
      <div className="orb orb-a" />
      <div className="orb orb-b" />
      <div className="orb orb-c" />
      <div className="noise" />
    </div>
  );
}

export function StatusStrip() {
  const { data: setup } = useSWR<any>("/setup", fetcher, { refreshInterval: 10000 });
  const { data: mode } = useSWR<any>("/trading/mode-status", fetcher, { refreshInterval: 10000 });
  const checks = setup?.checks || [];
  const byKey = Object.fromEntries(checks.map((c: any) => [c.key, c]));
  const bits = [
    { label: mode?.strategy_mode === "ai" ? "AI motor" : "Copy motor", ok: true, text: mode?.strategy_mode === "ai" ? "AI TRADE" : "COPY TRADE", icon: mode?.strategy_mode === "ai" ? BrainCircuit : CopyCheck },
    { label: "Listener", ok: !!byKey.listener?.ok, text: byKey.listener?.ok ? "Online" : "Sinyal yok", icon: Radio },
    { label: "Helius", ok: !!byKey.helius?.ok, text: byKey.helius?.ok ? "Hazır" : "Eksik", icon: Server },
    { label: "Motor", ok: !!setup?.engine_enabled, text: setup?.engine_enabled ? "Açık" : "Kapalı", icon: Zap },
  ];
  return (
    <div className="status-strip">
      {bits.map((b) => {
        const Icon = b.icon;
        return (
          <div key={b.label} className={b.ok ? "status-chip ok" : "status-chip bad"} title={`${b.label}: ${b.text}`}>
            <Icon size={13} />
            <span>{b.label}</span>
            <b>{b.text}</b>
          </div>
        );
      })}
      <div className="ml-auto hidden items-center gap-2 text-[11px] muted xl:flex">
        <Keyboard size={13} /> <span>Ctrl+K komut paneli</span>
      </div>
    </div>
  );
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const { data: logs } = useSWR<any[]>(open ? "/logs?limit=40" : null, fetcher, { refreshInterval: open ? 8000 : 0 });
  const warnings = (logs || []).filter((l) => ["warning", "error"].includes(String(l.level))).length;
  return (
    <div className="relative">
      <button className="icon-btn" onClick={() => setOpen((v) => !v)} title="Bildirim merkezi">
        <Bell size={16} />
        {warnings > 0 && <span className="notif-dot">{Math.min(9, warnings)}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="font-extrabold">Bildirim Merkezi</div>
              <div className="text-xs muted">Son kritik loglar ve sistem olayları</div>
            </div>
            <button className="btn-ghost" onClick={() => setOpen(false)}><X size={14} /></button>
          </div>
          <div className="space-y-2">
            {(logs || []).slice(0, 12).map((l) => {
              const isBad = String(l.level) === "error";
              const isWarn = String(l.level) === "warning";
              return (
                <div key={l.id} className="notif-row">
                  <div className={isBad ? "notif-icon bad" : isWarn ? "notif-icon warn" : "notif-icon ok"}>
                    {isBad ? <XCircle size={14} /> : isWarn ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-bold">{l.message}</div>
                    <div className="mt-0.5 text-[11px] muted">{l.category} · {new Date(l.created_at).toLocaleTimeString("tr-TR")}</div>
                  </div>
                </div>
              );
            })}
            {!logs && <div className="rounded-2xl border border-dashed p-6 text-center text-xs muted">Açılıyor…</div>}
            {logs && logs.length === 0 && <div className="rounded-2xl border border-dashed p-6 text-center text-xs muted">Henüz bildirim yok.</div>}
          </div>
          <Link className="mt-3 flex items-center justify-center gap-2 rounded-2xl border px-3 py-2 text-xs font-bold" style={{ borderColor: "var(--border)", background: "var(--bg2)" }} href="/logs" onClick={() => setOpen(false)}>
            Tüm logları aç <ChevronRight size={14} />
          </Link>
        </div>
      )}
    </div>
  );
}

export function CommandPalette() {
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const { data: risk, mutate } = useSWR<any>("/settings/risk", fetcher, { refreshInterval: 15000 });
  const mode = String(risk?.value?.strategy_mode || "copy") === "ai" ? "ai" : "copy";
  const links = MODE_LINKS[mode];
  const all = [
    ...links,
    { href: "/settings/live", label: "Canlı Kurulum", hint: "PumpPortal / canlı işlem ayarları", icon: Radio },
    { href: "/settings/api", label: "API ve RPC", hint: "Helius, RPC, provider ayarları", icon: Server },
    { href: "/logs", label: "Teknik Loglar", hint: "Hata ve uyarı kayıtları", icon: Bell },
  ];
  const filtered = all.filter((x) => `${x.label} ${x.hint}`.toLowerCase().includes(q.toLowerCase())).slice(0, 10);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault(); setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  async function switchMode(next: Mode) {
    if (!risk?.value) return;
    await apiSend("/settings/risk", "PUT", { value: { ...risk.value, strategy_mode: next } });
    await mutate();
    toast("success", `${next === "ai" ? "AI TRADE" : "COPY TRADE"} aktif`);
    setOpen(false);
    router.push(next === "ai" ? "/ai" : "/copy");
  }
  return (
    <>
      <button className="command-trigger" onClick={() => setOpen(true)} title="Komut paneli">
        <Search size={15} /><span className="hidden md:inline">Ara / Komut</span><kbd>Ctrl K</kbd>
      </button>
      {open && (
        <div className="cmd-overlay" onMouseDown={() => setOpen(false)}>
          <div className="cmd-panel" onMouseDown={(e) => e.stopPropagation()}>
            <div className="cmd-input-row">
              <Command size={18} className="brand" />
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Sayfa, ayar, mod veya işlem ara…" />
              <button onClick={() => setOpen(false)}><X size={16} /></button>
            </div>
            <div className="grid gap-2 p-3 sm:grid-cols-2">
              <button className={mode === "ai" ? "cmd-mode active" : "cmd-mode"} onClick={() => switchMode("ai")}>
                <BrainCircuit size={18} /><span><b>AI TRADE</b><small>Token karar motoru</small></span>
              </button>
              <button className={mode === "copy" ? "cmd-mode active" : "cmd-mode"} onClick={() => switchMode("copy")}>
                <CopyCheck size={18} /><span><b>COPY TRADE</b><small>Cüzdan kopyalama</small></span>
              </button>
            </div>
            <div className="max-h-[420px] overflow-y-auto px-3 pb-3">
              {filtered.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <button key={item.href} className={active ? "cmd-row active" : "cmd-row"} onClick={() => { router.push(item.href); setOpen(false); }}>
                    <Icon size={17} />
                    <span className="min-w-0 flex-1 text-left"><b>{item.label}</b><small>{item.hint}</small></span>
                    <ChevronRight size={15} />
                  </button>
                );
              })}
              {filtered.length === 0 && <div className="rounded-2xl border border-dashed p-8 text-center text-sm muted">Sonuç yok.</div>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function TinyLine({ data, dataKey = "pnl" }: { data?: ChartPoint[]; dataKey?: string }) {
  const rows = (data || []).slice(-28);
  if (!rows.length) return <div className="chart-empty">Grafik için veri bekleniyor</div>;
  return (
    <ResponsiveContainer width="100%" height={72}>
      <AreaChart data={rows} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
        <defs>
          <linearGradient id="tinyArea" x1="0" x2="0" y1="0" y2="1">
            <stop offset="5%" stopColor="currentColor" stopOpacity={0.28} />
            <stop offset="95%" stopColor="currentColor" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey={dataKey} stroke="currentColor" fill="url(#tinyArea)" strokeWidth={2} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function PremiumLineChart({ data, dataKey = "pnl", label = "Equity" }: { data?: ChartPoint[]; dataKey?: string; label?: string }) {
  const rows = (data || []).slice(-80);
  return (
    <div className="premium-chart-card">
      <div className="mb-3 flex items-center justify-between">
        <div><b>{label}</b><div className="text-xs muted">Kapanan işlemlerle oluşan eğri</div></div>
        <LineChartIcon size={18} className="brand" />
      </div>
      {rows.length ? (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={rows} margin={{ top: 10, right: 10, left: -24, bottom: 0 }}>
            <defs>
              <linearGradient id="areaMain" x1="0" x2="0" y1="0" y2="1">
                <stop offset="5%" stopColor="currentColor" stopOpacity={0.25} />
                <stop offset="95%" stopColor="currentColor" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <XAxis dataKey="t" hide />
            <YAxis tick={{ fontSize: 11 }} width={48} />
            <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14 }} />
            <Area type="monotone" dataKey={dataKey} stroke="currentColor" fill="url(#areaMain)" strokeWidth={2.6} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      ) : <div className="chart-empty h-[220px]">Equity verisi oluşmadı</div>}
    </div>
  );
}

export function PremiumBarChart({ data, xKey = "reason", yKey = "count", label = "Dağılım" }: { data?: ChartPoint[]; xKey?: string; yKey?: string; label?: string }) {
  const rows = (data || []).slice(0, 9).map((r, i) => ({ ...r, label: String(r[xKey] || "—").slice(0, 18), idx: i }));
  return (
    <div className="premium-chart-card">
      <div className="mb-3 flex items-center justify-between"><b>{label}</b><Gauge size={18} className="brand" /></div>
      {rows.length ? (
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={rows} margin={{ top: 4, right: 8, left: -28, bottom: 20 }}>
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} angle={-16} textAnchor="end" height={48} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14 }} />
            <Bar dataKey={yKey} radius={[10, 10, 4, 4]} fill="currentColor" />
          </BarChart>
        </ResponsiveContainer>
      ) : <div className="chart-empty h-[230px]">Dağılım verisi yok</div>}
    </div>
  );
}

export function PremiumDonut({ data, label = "Dağılım" }: { data?: { name: string; value: number }[]; label?: string }) {
  const rows = (data || []).filter((x) => Number(x.value) > 0).slice(0, 6);
  return (
    <div className="premium-chart-card">
      <div className="mb-3 flex items-center justify-between"><b>{label}</b><CircleDollarSign size={18} className="brand" /></div>
      {rows.length ? (
        <div className="grid gap-3 md:grid-cols-[170px_1fr]">
          <ResponsiveContainer width="100%" height={170}>
            <PieChart>
              <Pie data={rows} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78} paddingAngle={4}>
                {rows.map((_, i) => <Cell key={i} fill="currentColor" opacity={0.95 - i * 0.1} />)}
              </Pie>
              <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-2 self-center">
            {rows.map((x, i) => <div key={x.name} className="flex items-center justify-between rounded-xl border px-3 py-2 text-xs" style={{ borderColor: "var(--border)", background: "var(--bg2)", opacity: 1 - i * 0.04 }}><span className="truncate muted">{x.name}</span><b>{x.value}</b></div>)}
          </div>
        </div>
      ) : <div className="chart-empty h-[170px]">Çıkış verisi yok</div>}
    </div>
  );
}

export function DecisionDrawer({ open, onClose, item, mode = "ai" }: { open: boolean; onClose: () => void; item: any; mode?: Mode }) {
  if (!open) return null;
  const token = item?.token_mint || item?.token?.mint || item?.token || item?.context?.token;
  const pnl = Number(item?.pnl_sol ?? item?.realized_pnl_sol ?? 0);
  return (
    <div className="drawer-shell" onMouseDown={onClose}>
      <aside className="drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-bold uppercase tracking-[.25em] muted">İşlem açıklaması</div>
            <h2 className="mt-1 text-2xl font-black">{mode === "ai" ? "AI Karar Detayı" : "Copy Karar Detayı"}</h2>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="space-y-3">
          <div className="detail-hero">
            <div className="text-xs muted">Token</div>
            <div className="mt-1 font-mono text-lg font-black">{shortAddr(token)}</div>
            {token && <Link className="mt-3 inline-flex items-center gap-2 text-xs font-bold brand" href={`/tokens/${token}`}>Token detayını aç <ExternalLink size={13} /></Link>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="mini-kpi"><span>Karar</span><b>{item?.status || item?.action || item?.side || "—"}</b></div>
            <div className="mini-kpi"><span>PnL</span><b style={{ color: pnl >= 0 ? "var(--emerald)" : "var(--rose)" }}>{fmtNum(pnl, 4)} SOL</b></div>
            <div className="mini-kpi"><span>Giriş</span><b>{item?.entry_price_sol ? fmtNum(item.entry_price_sol, 10) : "—"}</b></div>
            <div className="mini-kpi"><span>Çıkış</span><b>{item?.exit_price_sol ? fmtNum(item.exit_price_sol, 10) : "—"}</b></div>
            <div className="mini-kpi"><span>Hold</span><b>{item?.hold_minutes ? `${fmtNum(item.hold_minutes, 1)} dk` : "—"}</b></div>
            <div className="mini-kpi"><span>Skor</span><b>{item?.entry_score ?? item?.token_score ?? item?.token?.score ?? "—"}</b></div>
          </div>
          <div className="explain-box good">
            <b>Neden aldı?</b>
            <p>{item?.entry_reason || item?.reason || item?.message || "Bu işlem için kayıtlı açıklama bulunamadı."}</p>
          </div>
          <div className="explain-box warn">
            <b>Neden çıktı / neden kapanmadı?</b>
            <p>{item?.exit_reason || item?.exit_reason_raw || (item?.status === "open" ? "Pozisyon hâlâ açık; çıkış motoru bekliyor." : "Çıkış nedeni kaydı yok.")}</p>
          </div>
          <div className="explain-box">
            <b>Kontrol notu</b>
            <p>Canlı PnL tahmini olabilir. Gerçek cüzdan bakiyesi ve on-chain portföy her zaman referanstır.</p>
          </div>
        </div>
      </aside>
    </div>
  );
}

export function PremiumEmpty({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="premium-empty">
      <div className="empty-planet"><Sparkles size={28} /></div>
      <div className="mt-3 text-lg font-black">{title}</div>
      <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed muted">{text}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function SpotlightCard({ icon, title, text, href, tone = "var(--brand)" }: { icon: React.ReactNode; title: string; text: string; href?: string; tone?: string }) {
  const body = (
    <div className="spotlight-card" style={{ ["--spot" as any]: tone }}>
      <div className="spot-ico">{icon}</div>
      <div className="min-w-0 flex-1">
        <div className="font-extrabold">{title}</div>
        <div className="mt-1 text-xs leading-relaxed muted">{text}</div>
      </div>
      {href && <ChevronRight size={16} className="muted" />}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

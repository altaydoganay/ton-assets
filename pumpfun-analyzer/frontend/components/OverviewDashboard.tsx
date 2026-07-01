"use client";
import Link from "next/link";
import useSWR from "swr";
import { apiSend, fetcher, fmtNum, shortAddr } from "@/lib/api";
import { InfoTip } from "@/components/ui";
import { useToast } from "@/components/Toast";
import {
  BrainCircuit, CopyCheck, ArrowRight, FlaskConical, Zap, ShieldCheck, Coins, Trophy,
  Activity, Gauge, ScrollText, TrendingUp, TrendingDown, Radar, CheckCircle2, Wallet,
} from "lucide-react";
import { PremiumLineChart, TinyLine } from "@/components/PremiumUI";
import { AiDecisionFlow } from "@/components/AiDecisionFlow";
import { TokenAvatar, useTokenMeta } from "@/components/TokenAvatar";

type Mode = "ai" | "copy";

const MODES = {
  ai: { title: "AI TRADE", icon: BrainCircuit, tone: "var(--violet)", desc: "Token fırsatlarını kendi analiz eder",
        long: "Başkasının cüzdanını değil, token'ın kendisini görür: puanlar, riskleri tartar, neden aldığını/almadığını kaydeder.", href: "/ai" },
  copy: { title: "COPY TRADE", icon: CopyCheck, tone: "var(--emerald)", desc: "Kaliteli cüzdanları kopyalar",
        long: "Kaliteli lider cüzdanları izler; copyability, bağımsızlık filtresi ve leader-watch güvenliğiyle çalışır.", href: "/copy" },
};

function ModeCard({ id, active, onSelect }: { id: Mode; active: boolean; onSelect: () => void }) {
  const cfg = MODES[id];
  const Icon = cfg.icon;
  return (
    <button onClick={onSelect} className="text-left" style={{ ["--mode-tone" as any]: cfg.tone }}>
      <div className={`relative overflow-hidden rounded-3xl border p-5 transition ${active ? "ring-2" : ""}`}
        style={{
          borderColor: active ? cfg.tone : "var(--border)",
          background: active
            ? `radial-gradient(600px 200px at 0% 0%, color-mix(in srgb, ${cfg.tone} 26%, transparent), transparent 70%), color-mix(in srgb, var(--card) 90%, transparent)`
            : "color-mix(in srgb, var(--card) 88%, transparent)",
          boxShadow: active ? `0 20px 60px -30px ${cfg.tone}` : undefined,
        } as any}>
        {active && <span className="absolute right-4 top-4 rounded-full px-2.5 py-1 text-[10px] font-black tracking-wider text-white" style={{ background: cfg.tone }}>● AKTİF MOD</span>}
        <div className="flex items-center gap-3">
          <div className="grid h-14 w-14 place-items-center rounded-2xl text-white" style={{ background: `linear-gradient(135deg, ${cfg.tone}, color-mix(in srgb, ${cfg.tone} 60%, #000))` }}>
            <Icon size={28} />
          </div>
          <div>
            <div className="flex items-center gap-2 text-2xl font-black tracking-tight">{cfg.title}<InfoTip title={cfg.title}>{cfg.long}</InfoTip></div>
            <div className="text-sm muted">{cfg.desc}</div>
          </div>
        </div>
      </div>
    </button>
  );
}

function DecisionStudioHero({ strategy, ai, dataStatus }: { strategy: Mode; ai: any; dataStatus?: string }) {
  const cfg = MODES[strategy];
  const Icon = cfg.icon;
  const last = ai?.decisions_feed?.[0]?.created_at || ai?.last_decision_at;
  const lastTxt = last ? new Date(last).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "—";
  return (
    <div className="relative overflow-hidden rounded-3xl border p-6" style={{
      borderColor: `color-mix(in srgb, ${cfg.tone} 30%, var(--border))`,
      background: `radial-gradient(700px 260px at 88% -10%, color-mix(in srgb, ${cfg.tone} 22%, transparent), transparent 62%), radial-gradient(520px 240px at 0% 120%, color-mix(in srgb, var(--brand) 16%, transparent), transparent 70%), color-mix(in srgb, var(--card) 86%, transparent)`,
    }}>
      <div className="relative z-10 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-black tracking-tight md:text-4xl">
            {strategy === "ai" ? "AI Decision Studio" : "Copy Trade Studio"}
          </h2>
          <p className="mt-1 text-sm muted">{strategy === "ai" ? "Token fırsatlarını canlı analiz eder" : "Kaliteli liderleri canlı izler"}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <span className="hchip"><Radar size={14} className="text-emerald-500" /> Piyasa Tarama {dataStatus === "down" ? "Kısıtlı" : "Aktif"}</span>
            <span className="hchip"><Activity size={14} /> Son karar: {lastTxt}</span>
            <span className="hchip"><ShieldCheck size={14} /> {ai?.blocked_decisions ?? 0} filtrelendi</span>
          </div>
        </div>
        <div className="ai-brain-orb hidden shrink-0 sm:grid" style={{ ["--mode-tone" as any]: cfg.tone } as any}>
          <Icon size={40} className="text-white" />
        </div>
      </div>
    </div>
  );
}

function SparkStat({ label, value, sub, tone, series, up }: { label: string; value: string; sub?: string; tone: string; series?: any[]; up?: boolean }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border p-4" style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--card) 90%, transparent)" }}>
      <div className="text-xs muted">{label}</div>
      <div className="mt-1 text-2xl font-black tracking-tight" style={{ color: tone }}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] muted">{sub}</div>}
      {series && series.length > 1 && (
        <div className="mt-2 h-10 opacity-90"><TinyLine data={series} /></div>
      )}
      <div className="pointer-events-none absolute -right-6 -top-6 h-16 w-16 rounded-full" style={{ background: tone, opacity: 0.1, filter: "blur(14px)" }} />
    </div>
  );
}

function RiskGauge({ risk }: { risk: any }) {
  const v = risk?.value || {};
  // Basit risk skoru (0-100): büyük pozisyon + gevşek stop + çok eşzamanlı = yüksek.
  let score = 20;
  score += Math.min(30, (Number(v.max_position_sol) || 0.01) * 60);
  score += (Number(v.stop_loss_pct) || 0) > 0 ? 0 : 18;
  score += Math.min(20, (Number(v.max_open_positions_per_token) || 1) * 6);
  score += v.mode === "live" ? 14 : 0;
  score = Math.max(4, Math.min(96, Math.round(score)));
  const tone = score < 40 ? "var(--emerald)" : score < 70 ? "var(--amber)" : "var(--rose)";
  const tag = score < 40 ? "Düşük Risk" : score < 70 ? "Orta Risk" : "Yüksek Risk";
  const checks = [
    ["Pozisyon büyüklüğü", (Number(v.max_position_sol) || 0.01) <= 0.05],
    ["Stop-loss kullanımı", (Number(v.stop_loss_pct) || 0) > 0],
    ["Günlük zarar limiti", (Number(v.max_daily_loss_sol) || 0) > 0],
    ["Paper doğrulama", v.mode !== "live"],
  ] as const;
  return (
    <div className="card">
      <div className="mb-2 flex items-center gap-2"><Gauge size={18} /><b>Risk Profili</b><InfoTip title="Risk profili">Mevcut risk ayarlarından türetilen kaba risk skoru. Düşük = daha temkinli.</InfoTip></div>
      <div className="flex items-center gap-4">
        <div className="relative grid h-24 w-24 shrink-0 place-items-center">
          <svg viewBox="0 0 100 100" className="h-24 w-24 -rotate-90">
            <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border)" strokeWidth="10" />
            <circle cx="50" cy="50" r="42" fill="none" stroke={tone} strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${(score / 100) * 264} 264`} />
          </svg>
          <div className="absolute text-center">
            <div className="text-xl font-black" style={{ color: tone }}>{score}</div>
            <div className="text-[9px] muted">/100</div>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold" style={{ color: tone }}>{tag}</div>
          <div className="mt-2 space-y-1">
            {checks.map(([lbl, ok]) => (
              <div key={lbl} className="flex items-center justify-between text-xs">
                <span className="muted">{lbl}</span>
                <span className={ok ? "text-emerald-500" : "text-amber-500"}>{ok ? "İyi" : "Dikkat"}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <Link href="/settings/risk" className="btn mt-3 w-full justify-center text-xs">Risk ayarları <ArrowRight size={13} /></Link>
    </div>
  );
}

function PortfolioMini() {
  const { data: pf } = useSWR<any>("/stats/wallet-portfolio?fresh=true&history_fallback=false&das_balance=false", fetcher, { refreshInterval: 15000, shouldRetryOnError: false });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 20000 });
  const val = pf?.total_value_sol ?? pf?.sol_balance;
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between">
        <b className="flex items-center gap-2"><Wallet size={16} /> Portföy Özeti</b>
        <Link href="/positions" className="text-xs muted">Detay <ArrowRight size={12} className="inline" /></Link>
      </div>
      <div className="text-3xl font-black">{val != null ? `${fmtNum(val, 3)} SOL` : "—"}</div>
      <div className="text-[11px] muted">{pf?.token_count != null ? `${pf.token_count} token · ${fmtNum(pf?.sol_balance, 3)} SOL nakit` : "cüzdan bağla ya da TRADING_WALLET_ADDRESS ayarla"}</div>
      <div className="mt-2 h-24"><TinyLine data={(perf?.curve || []).map((c: any) => ({ pnl: c.pnl ?? c.equity ?? c.value ?? 0 }))} /></div>
    </div>
  );
}

function OpenPositionsMini() {
  const { data: positions } = useSWR<any[]>("/stats/positions", fetcher, { refreshInterval: 10000 });
  const rows = (positions || []).slice(0, 4);
  const meta = useTokenMeta(rows.map((p) => p.token_mint));
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between">
        <b className="flex items-center gap-2"><Coins size={16} /> Açık Pozisyonlar</b>
        <Link href="/positions" className="text-xs muted">Tümü <ArrowRight size={12} className="inline" /></Link>
      </div>
      {rows.length === 0 ? (
        <div className="py-4 text-center text-sm muted">Açık pozisyon yok.</div>
      ) : rows.map((p) => {
        const pnl = p.unrealized_pnl_sol;
        const up = (pnl ?? 0) >= 0;
        return (
          <Link key={p.position_id || p.token_mint} href={`/tokens/${p.token_mint}`}
            className="flex items-center gap-3 border-b py-2 last:border-0 hover:opacity-90" style={{ borderColor: "var(--border)" }}>
            <TokenAvatar mint={p.token_mint} meta={{ mint: p.token_mint, symbol: p.token_symbol, name: p.token_name, image_url: p.token_image }} size={32} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold">{p.token_symbol || p.token_name || shortAddr(p.token_mint)}</div>
              <div className="text-[11px] muted">{fmtNum(p.cost_sol ?? p.sol_amount, 3)} SOL</div>
            </div>
            <div className="text-right text-sm font-bold" style={{ color: pnl == null ? "var(--muted)" : up ? "var(--emerald)" : "var(--rose)" }}>
              {pnl == null ? "—" : `${up ? "+" : ""}${fmtNum(pnl, 3)}`}
              {p.unrealized_pnl_pct != null && <div className="text-[10px]">{(p.unrealized_pnl_pct * 100).toFixed(1)}%</div>}
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function CopySummary({ ov }: { ov: any }) {
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 20000 });
  const tracked = ov?.wallets?.tracked ?? 0;
  const wr = perf?.win_rate;
  return (
    <div className="card">
      <div className="mb-3 flex items-center gap-2"><CopyCheck size={18} /><b>Copy Trade Özeti</b></div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div><div className="text-2xl font-black">{tracked}</div><div className="text-[11px] muted">Takip cüzdanı</div></div>
        <div><div className="text-2xl font-black text-emerald-500">{wr != null ? `%${fmtNum(wr * 100, 0)}` : "—"}</div><div className="text-[11px] muted">Başarı oranı</div></div>
        <div><div className="text-2xl font-black" style={{ color: (ov?.pnl?.paper_sol ?? 0) >= 0 ? "var(--emerald)" : "var(--rose)" }}>{fmtNum(ov?.pnl?.paper_sol ?? 0, 3)}</div><div className="text-[11px] muted">Paper PnL (SOL)</div></div>
      </div>
      <Link href="/copy" className="btn mt-3 w-full justify-center text-xs">Copy panelini gör <ArrowRight size={13} /></Link>
    </div>
  );
}

function RecentLogs() {
  const { data: logs } = useSWR<any[]>("/logs?limit=7", fetcher, { refreshInterval: 8000 });
  const tone: Record<string, string> = { warning: "var(--amber)", error: "var(--rose)", info: "var(--sky)" };
  const catTone: Record<string, string> = { trading: "var(--emerald)", ai_scan: "var(--violet)", settings: "var(--sky)", system: "var(--muted)" };
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between">
        <b className="flex items-center gap-2"><ScrollText size={16} /> Son Loglar</b>
        <Link href="/logs" className="text-xs muted">Tümü <ArrowRight size={12} className="inline" /></Link>
      </div>
      <div className="space-y-1.5">
        {(logs || []).slice(0, 7).map((l) => (
          <div key={l.id} className="flex items-start gap-2 text-xs">
            <span className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase"
              style={{ color: catTone[l.category] || "var(--muted)", background: `color-mix(in srgb, ${catTone[l.category] || "var(--muted)"} 14%, transparent)` }}>
              {l.category}
            </span>
            <span className="min-w-0 flex-1 truncate" style={{ color: tone[l.level] || "var(--text)" }} title={l.message}>{l.message}</span>
            <span className="shrink-0 muted">{l.created_at ? new Date(l.created_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : ""}</span>
          </div>
        ))}
        {(!logs || logs.length === 0) && <div className="py-3 text-center text-xs muted">Log yok.</div>}
      </div>
    </div>
  );
}

export function OverviewDashboard() {
  const toast = useToast();
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: risk, mutate } = useSWR<any>("/settings/risk", fetcher, { refreshInterval: 12000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 15000 });
  const { data: ts } = useSWR<any[]>("/stats/timeseries?days=14", fetcher, { refreshInterval: 30000 });
  const { data: ai } = useSWR<any>("/trading/ai-center?minutes=60&limit=40", fetcher, { refreshInterval: 8000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 10000 });
  const { data: health } = useSWR<any>("/health", fetcher, { refreshInterval: 12000 });

  const strategy = ((risk?.value?.strategy_mode || "copy") as Mode);
  async function setMode(next: Mode) {
    if (!risk?.value) return;
    try {
      await apiSend("/settings/risk", "PUT", { value: { ...risk.value, strategy_mode: next } });
      await mutate();
      toast("success", `${MODES[next].title} aktif`);
    } catch (e: any) { toast("error", e?.message || "Mod değiştirilemedi"); }
  }

  const equity = (perf?.curve || []).map((c: any) => ({ pnl: c.pnl ?? c.equity ?? c.value ?? 0 }));
  const discSeries = (ts || []).map((x: any) => ({ pnl: x.discovered ?? 0 }));
  const providers = health?.providers || [];
  const okCount = providers.filter((p: any) => p.status === "ok").length;
  const dataHealthPct = providers.length ? Math.round((okCount / providers.length) * 100) : (health?.market_data_reliable === false ? 40 : 100);
  const todayPnl = sum?.today_realized_pnl_sol ?? 0;

  return (
    <div className="space-y-5">
      {/* Mod kartları */}
      <div className="grid gap-4 md:grid-cols-2">
        <ModeCard id="ai" active={strategy === "ai"} onSelect={() => setMode("ai")} />
        <ModeCard id="copy" active={strategy === "copy"} onSelect={() => setMode("copy")} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
        {/* SOL sütun */}
        <div className="space-y-4">
          <DecisionStudioHero strategy={strategy} ai={ai} dataStatus={health?.data_status} />

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SparkStat label="Günlük PnL" value={`${todayPnl >= 0 ? "+" : ""}${fmtNum(todayPnl, 3)} SOL`} tone={todayPnl >= 0 ? "var(--emerald)" : "var(--rose)"} sub="bugün (paper)" series={equity} />
            <SparkStat label="Açık Pozisyon" value={`${sum?.open_positions ?? 0}`} tone="var(--sky)" sub={`${fmtNum(sum?.open_exposure_sol ?? 0, 3)} SOL risk`} />
            <SparkStat label="Token Sinyali" value={`${ai?.decisions ?? 0}`} tone="var(--violet)" sub={`${ai?.opened_decisions ?? 0} alım · ${ai?.blocked_decisions ?? 0} filtre`} series={discSeries} />
            <SparkStat label="Veri Sağlığı" value={`%${dataHealthPct}`} tone={dataHealthPct >= 80 ? "var(--emerald)" : dataHealthPct >= 50 ? "var(--amber)" : "var(--rose)"} sub={`${okCount}/${providers.length || "?"} sağlayıcı ok`} />
          </div>

          <AiDecisionFlow strategy={strategy} limit={8} />
        </div>

        {/* SAĞ sütun */}
        <div className="space-y-4">
          <PortfolioMini />
          <OpenPositionsMini />
          <ProviderHealthCard health={health} />
        </div>
      </div>

      {/* Alt satır */}
      <div className="grid gap-4 lg:grid-cols-3">
        <RiskGauge risk={risk} />
        <CopySummary ov={ov} />
        <RecentLogs />
      </div>

      <PremiumLineChart data={perf?.curve || []} label="Paper Equity Curve" />
    </div>
  );
}

function ProviderHealthCard({ health }: { health: any }) {
  const providers = health?.providers || [];
  const meta: Record<string, string> = { ok: "var(--emerald)", degraded: "var(--amber)", down: "var(--rose)", unknown: "var(--muted)" };
  const label: Record<string, string> = { ok: "Sağlıklı", degraded: "Kısıtlı", down: "Down", unknown: "—" };
  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <b className="flex items-center gap-2"><Gauge size={16} /> Provider Sağlığı</b>
        <span className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: meta[health?.data_status || "unknown"], background: `color-mix(in srgb, ${meta[health?.data_status || "unknown"]} 14%, transparent)` }}>
          {label[health?.data_status || "unknown"]}
        </span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-2"><Wallet size={14} /> Zincir · {health?.chain_provider ?? "—"}</span><span className="text-xs muted">RPC</span>
        </div>
        <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-2"><Activity size={14} /> Piyasa · {health?.market_provider ?? "—"}</span>
          {health?.market_data_reliable === false ? <span className="text-xs text-red-500">güvenilmez</span> : <span className="text-xs text-emerald-500">ok</span>}
        </div>
        {providers.slice(0, 4).map((p: any) => (
          <div key={`${p.kind}:${p.name}`} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
            <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: meta[p.status] || "var(--muted)" }} />{p.name}</span>
            <span className="text-xs" style={{ color: meta[p.status] || "var(--muted)" }}>{p.avg_latency_ms != null ? `${p.avg_latency_ms}ms` : (label[p.status] || "—")}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-emerald-500"><CheckCircle2 size={13} /> {health?.status === "ok" ? "Tüm sistemler normal" : "Sistem kısıtlı"}</div>
      <Link href="/health" className="btn mt-2 w-full justify-center text-xs">Tüm sistem sağlığı <ArrowRight size={13} /></Link>
    </div>
  );
}

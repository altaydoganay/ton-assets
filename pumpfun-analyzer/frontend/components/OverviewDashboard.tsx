"use client";
import Link from "next/link";
import useSWR from "swr";
import { apiSend, fetcher, fmtNum } from "@/lib/api";
import { StatCard, InfoTip, Callout } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { PageHeader } from "@/components/Confidence";
import {
  BrainCircuit, CopyCheck, ArrowRight, FlaskConical, Zap, ShieldCheck,
  Coins, Trophy, Sparkles, Gauge, Activity, Wallet, Bell, Rocket,
} from "lucide-react";
import { PremiumBarChart, PremiumDonut, PremiumLineChart, SpotlightCard, TinyLine } from "@/components/PremiumUI";

type Mode = "ai" | "copy";

const MODES = {
  ai: {
    title: "AI TRADE", icon: BrainCircuit, tone: "var(--violet)", subtitle: "Token fırsat motoru",
    desc: "Başkasının cüzdanını ana karar yapmaz. Tokenı görür, puanlar, riskleri tartar, neden aldığını veya neden almadığını kaydeder.",
    bullets: ["Token bazlı karar", "AI Decision Center", "Neden almadım hunisi", "Paper önce, canlı kilitli"], href: "/ai",
  },
  copy: {
    title: "COPY TRADE", icon: CopyCheck, tone: "var(--emerald)", subtitle: "Cüzdan kopyalama motoru",
    desc: "Kaliteli lider cüzdanları izler. Copyability, bağımsızlık filtresi ve leader-watch güvenliğiyle çalışır.",
    bullets: ["Cüzdan kalite skoru", "10sn copyability", "Leader-watch", "Ghost pozisyon temizliği"], href: "/copy",
  },
};

function ModeCard({ id, active, risk, mutate }: { id: Mode; active: boolean; risk: any; mutate: () => void }) {
  const cfg = MODES[id];
  const Icon = cfg.icon;
  const toast = useToast();
  async function select() {
    if (!risk?.value) return toast("info", "Ayarlar yükleniyor");
    try {
      await apiSend("/settings/risk", "PUT", { value: { ...risk.value, strategy_mode: id } });
      await mutate();
      toast("success", `${cfg.title} aktif edildi`);
    } catch (e: any) { toast("error", e?.message || "Mod seçilemedi"); }
  }
  return (
    <div className={active ? "mode-hero-card premium-choice active" : "mode-hero-card premium-choice"} style={{ ["--mode-tone" as any]: cfg.tone }}>
      <div className="choice-glow" />
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mode-hero-icon"><Icon size={26} /></div>
          <div>
            <div className="flex items-center gap-2 text-2xl font-black tracking-tight">
              {cfg.title}
              <InfoTip title={cfg.title}>{cfg.desc}</InfoTip>
            </div>
            <div className="mt-1 text-sm font-semibold muted">{cfg.subtitle}</div>
          </div>
        </div>
        {active && <span className="status-pill good">Aktif</span>}
      </div>
      <p className="mt-4 text-sm leading-relaxed muted">{cfg.desc}</p>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {cfg.bullets.map((b) => <div key={b} className="mode-bullet">✓ {b}</div>)}
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <button className={active ? "btn-primary" : "btn"} onClick={select}>{active ? "Seçili mod" : `${cfg.title} seç`}</button>
        <Link className="btn" href={cfg.href}>Panele git <ArrowRight size={15} /></Link>
      </div>
    </div>
  );
}

function ProviderHealthCard() {
  const { data: h } = useSWR<any>("/health", fetcher, { refreshInterval: 10000 });
  const providers = h?.providers || [];
  const meta: Record<string, string> = {
    ok: "var(--emerald)", degraded: "var(--amber)", down: "var(--rose)", unknown: "var(--muted)",
  };
  const label: Record<string, string> = { ok: "Sağlıklı", degraded: "Kısıtlı", down: "Down", unknown: "—" };
  return (
    <div className="premium-chart-card">
      <div className="mb-3 flex items-center justify-between">
        <b className="flex items-center gap-2"><Gauge size={18} /> Veri Sağlayıcı Sağlığı</b>
        <span className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: meta[h?.data_status || "unknown"], background: `color-mix(in srgb, ${meta[h?.data_status || "unknown"]} 14%, transparent)` }}>
          {label[h?.data_status || "unknown"]}
        </span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-2"><Wallet size={14} /> Zincir · {h?.chain_provider ?? "—"}</span>
          <span className="text-xs muted">RPC</span>
        </div>
        <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
          <span className="flex items-center gap-2"><Activity size={14} /> Piyasa · {h?.market_provider ?? "—"}</span>
          {h?.market_data_reliable === false
            ? <span className="text-xs text-red-500">güvenilmez</span>
            : <span className="text-xs text-emerald-500">ok</span>}
        </div>
        {providers.slice(0, 4).map((p: any) => (
          <div key={`${p.kind}:${p.name}`} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: meta[p.status] || "var(--muted)" }} />
              {p.name} <span className="text-[11px] muted">{p.kind === "market" ? "piyasa" : "zincir"}</span>
            </span>
            <span className="text-xs" style={{ color: meta[p.status] || "var(--muted)" }}>
              {p.avg_latency_ms != null ? `${p.avg_latency_ms}ms` : label[p.status] || "—"}
            </span>
          </div>
        ))}
        {providers.length === 0 && (
          <div className="rounded-lg border border-dashed px-3 py-3 text-center text-xs muted" style={{ borderColor: "var(--border)" }}>
            Sağlayıcı çağrısı bekleniyor…
          </div>
        )}
      </div>
      <Link href="/health" className="btn mt-3 w-full justify-center text-xs">Tüm sistem sağlığı <ArrowRight size={13} /></Link>
    </div>
  );
}

export function OverviewDashboard() {
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: risk, mutate } = useSWR<any>("/settings/risk", fetcher, { refreshInterval: 12000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 15000 });
  const { data: ts } = useSWR<any[]>("/stats/timeseries?days=14", fetcher, { refreshInterval: 30000 });
  const { data: ai } = useSWR<any>("/trading/ai-center?minutes=60&limit=40", fetcher, { refreshInterval: 8000 });
  const { data: setup } = useSWR<any>("/setup", fetcher, { refreshInterval: 20000 });
  const strategy = ((risk?.value?.strategy_mode || "copy") as Mode);
  const mode = risk?.value?.mode || "paper";
  const activeCfg = MODES[strategy];
  const exitData = (ai?.exit_breakdown || []).map((x: any) => ({ name: x.reason, value: x.count }));
  const reasonData = ai?.funnel?.top_reasons || [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Altay Premium Kontrol Merkezi"
        subtitle="Önce modu seç. Sonra panel sadece o moda ait veriyi, kararları ve riskleri gösterir. Teknik loglar arkada kalır; günlük kullanım bu ekrandan başlar."
        icon={<Rocket size={22} />}
        action={<Link className="btn-primary" href={strategy === "ai" ? "/ai" : "/copy"}>Aktif panele git <ArrowRight size={15} /></Link>}
      />

      <div className="showcase-hero">
        <div className="showcase-grid" />
        <div className="relative z-10 grid gap-6 xl:grid-cols-[1.25fr_.75fr]">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.32em] muted">Premium trading cockpit</div>
            <h1 className="mt-3 text-4xl font-black tracking-tight md:text-6xl">
              <span className="gradient-text">{activeCfg.title}</span> ile net, sade ve ölçülebilir karar.
            </h1>
            <p className="mt-4 max-w-4xl text-sm leading-relaxed muted md:text-base">
              Panel iki ayrı ürün gibi davranır: AI Trade token fırsat motorudur, Copy Trade cüzdan kopyalama motorudur. Seçili olmayan motor arka planda işlem üretmez.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <span className="hchip"><FlaskConical size={14} /> İşlem modu: {mode}</span>
              <span className="hchip"><ShieldCheck size={14} /> Motor: {risk?.value?.enabled ? "açık" : "kapalı"}</span>
              <span className="hchip"><Zap size={14} /> Canlı onay: {risk?.value?.live_confirmed ? "var" : "yok"}</span>
              <span className="hchip"><Bell size={14} /> BUILD {setup?.build ?? "—"}</span>
            </div>
          </div>
          <div className="hero-terminal">
            <div className="flex items-center gap-2 text-xs muted"><span className="live-dot" /> Sistem özeti</div>
            <div className="mt-4 space-y-3">
              <div className="terminal-row"><span>paper_pnl</span><b>{fmtNum(ov?.pnl?.paper_sol || 0, 4)} SOL</b></div>
              <div className="terminal-row"><span>live_pnl_est</span><b>{fmtNum(ov?.pnl?.live_sol || 0, 4)} SOL</b></div>
              <div className="terminal-row"><span>tokens</span><b>{fmtNum(ov?.tokens?.total || 0, 0)}</b></div>
              <div className="terminal-row"><span>tracked_wallets</span><b>{fmtNum(ov?.wallets?.tracked || 0, 0)}</b></div>
            </div>
            <div className="mt-4 text-[11px] muted">Ctrl+K ile her sayfaya ve moda hızlı geçiş yapabilirsin.</div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ModeCard id="ai" active={strategy === "ai"} risk={risk} mutate={() => mutate()} />
        <ModeCard id="copy" active={strategy === "copy"} risk={risk} mutate={() => mutate()} />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <StatCard label="Paper PnL" value={`${fmtNum(ov?.pnl?.paper_sol || 0, 4)} SOL`} hint="Simülasyon sonucu" icon={<FlaskConical size={18} />} tone="var(--sky)" />
        <StatCard label="Live PnL" value={`${fmtNum(ov?.pnl?.live_sol || 0, 4)} SOL`} hint="Tahmini / on-chain ile kontrol" icon={<Zap size={18} />} tone="var(--amber)" />
        <StatCard label="Token" value={fmtNum(ov?.tokens?.total || 0, 0)} hint="Analiz edilen token" icon={<Coins size={18} />} tone="var(--violet)" />
        <StatCard label="Takip Cüzdanı" value={fmtNum(ov?.wallets?.tracked || 0, 0)} hint={strategy === "ai" ? "AI modunda pasif" : "Copy modunda aktif"} icon={<Trophy size={18} />} tone="var(--emerald)" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
        <PremiumLineChart data={perf?.curve || []} label="Paper Equity Curve" />
        <ProviderHealthCard />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <PremiumDonut data={exitData} label="AI Exit Sebepleri" />
        <div className="premium-chart-card text-[color:var(--brand)]">
          <div className="mb-2 flex items-center justify-between"><b>Keşif ritmi</b><Activity size={18} /></div>
          <TinyLine data={(ts || []).map((x) => ({ ...x, pnl: x.discovered }))} />
          <div className="mt-2 text-xs muted">Son 14 gün keşfedilen cüzdan ritmi</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
        <PremiumBarChart data={reasonData} label="AI Neden Almadım?" />
        <div className="grid gap-3 md:grid-cols-2">
          <SpotlightCard href="/ai" icon={<BrainCircuit size={20} />} title="AI Decision Center" text="Neden aldı, neden almadı, nerede çıktı ve paper performansı." tone="var(--violet)" />
          <SpotlightCard href="/positions" icon={<Wallet size={20} />} title="Gerçek Portföy" text="DB tahmini ile bağlı cüzdanın on-chain snapshot’ını ayır." tone="var(--sky)" />
          <SpotlightCard href="/health" icon={<Gauge size={20} />} title="Sistem Sağlığı" text="Listener, Helius, motor ve worker durumunu tek bakışta gör." tone="var(--emerald)" />
          <SpotlightCard href="/logs" icon={<Bell size={20} />} title="Bildirim ve Log" text="Kritik olayları filtrele, teknik detaylara gerektiğinde in." tone="var(--amber)" />
        </div>
      </div>

      <Callout kind="info">
        <b>Yeni kullanım mantığı:</b> Günlük kullanımda önce mod kartını seç, sonra AI için <b>AI Decision Center</b>, Copy için <b>Copy Trade Paneli</b> ekranına gir. Loglar artık ana ekran değil; teknik kayıt deposudur.
      </Callout>
    </div>
  );
}

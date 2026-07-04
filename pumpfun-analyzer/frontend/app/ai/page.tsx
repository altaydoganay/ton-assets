"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import {
  ArrowRight, BrainCircuit, CheckCircle2, Clock, FilterX, FlaskConical,
  Gauge, LineChart, ShieldCheck, Sparkles, TimerReset, TrendingDown,
  TrendingUp, Wallet, XCircle, Zap, RotateCcw, Trash2, Download,
} from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { Callout, InfoTip, StatCard } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { DecisionDrawer, PremiumBarChart, PremiumDonut, PremiumEmpty } from "@/components/PremiumUI";
import { TradeShareCard, downloadTradeCardPng, type TradeCardData } from "@/components/TradeShareCard";
import { apiSend, fetcher, fmtNum, shortAddr } from "@/lib/api";

// Kapanmış bir AI session'ını paylaşım kartı verisine çevirir (moonbag: kısmi
// satışlarda proceeds toplanır; oran ana paraya göredir).
function sessionToCard(t: any): TradeCardData | null {
  if (!t || t.status === "open" || t.pnl_sol == null) return null;
  const initial = Number(t.cost_sol || 0);
  const worth = Number(t.proceeds_sol ?? (initial + Number(t.pnl_sol || 0)));
  const pct = initial > 1e-9 ? ((worth - initial) / initial) * 100 : (Number(t.pnl_sol || 0) >= 0 ? 0 : -100);
  return {
    symbol: t.token?.symbol || String(t.token_mint || "").slice(0, 4).toUpperCase() || "TOKEN",
    pnlPct: pct, initialSol: initial, worthSol: worth,
    mode: "ai", kind: "paper", when: t.exit_time || t.entry_time,
  };
}

type WindowMinutes = 15 | 60 | 240 | 1440;

function profileLabel(profile?: string) {
  if (profile === "safe") return "Güvenli";
  if (profile === "opportunistic") return "Fırsatçı";
  return "Dengeli";
}

function pct(n?: number | null) {
  if (n === null || n === undefined) return "—";
  return `%${fmtNum(Number(n) * 100, 1)}`;
}

function sol(n?: number | null, digits = 4) {
  return `${fmtNum(Number(n || 0), digits)} SOL`;
}

function actionIcon(action?: string) {
  if (action === "opened") return <CheckCircle2 size={16} className="text-emerald-500" />;
  if (action === "blocked") return <XCircle size={16} className="text-amber-400" />;
  if (action === "exit") return <TrendingDown size={16} className="text-sky-400" />;
  return <Clock size={16} className="muted" />;
}

function recommendationTone(level?: string) {
  if (level === "bad") return "var(--rose)";
  if (level === "warn") return "var(--amber)";
  if (level === "good") return "var(--emerald)";
  return "var(--sky)";
}

// Çıkış sebebini anlama göre renklendir: kâr=yeşil, stop/rug=kırmızı,
// trailing=mavi, zaman/momentum=amber. Hem anahtar hem Türkçe etiketle eşleşir.
function exitTone(reason?: string): string {
  const s = (reason || "").toLowerCase();
  if (/(liq|rug|likidite|hard|sert stop|\bsl\b|stop-loss|dump)/.test(s)) return "var(--rose)";
  if (/(principal|ana para|10x|25x|\btp\b|take-profit|kâr|kar|kademeli|partial)/.test(s)) return "var(--emerald)";
  if (/(trail|takip eden|moonbag)/.test(s)) return "var(--sky)";
  if (/(time|zaman|momentum|stagnant|durgun|2x)/.test(s)) return "var(--amber)";
  return "var(--violet)";
}

export default function AiTradePage() {
  const [minutes, setMinutes] = useState<WindowMinutes>(60);
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const { data: risk } = useSWR<any>("/settings/risk", fetcher, { refreshInterval: 12000 });
  const { data: resetStatus, mutate: mutateResetStatus } = useSWR<any>("/trading/reset-status?scope=ai", fetcher, { refreshInterval: 10000 });
  const { data: center, mutate: mutateCenter } = useSWR<any>(`/trading/ai-center?minutes=${minutes}&limit=80`, fetcher, { refreshInterval: 5000 });
  const r = risk?.value || {};
  const s = center?.summary || {};
  const sessions = center?.sessions || [];
  const feed = center?.decision_feed || [];
  const reasons = center?.funnel?.top_reasons || [];
  const exits = center?.exit_breakdown || [];
  const recs = center?.recommendations || [];
  const activeAi = String(r.strategy_mode || "copy") === "ai";
  const paperMode = String(r.mode || "paper") === "paper";
  const [selected, setSelected] = useState<any>(null);
  const [showAllCards, setShowAllCards] = useState(false);
  const exitDonut = exits.map((x: any) => ({ name: x.reason, value: x.count }));
  // Tamamlanan işlemler → paylaşım kartları (en yeni önce)
  const tradeCards = (sessions as any[])
    .map(sessionToCard)
    .filter(Boolean) as TradeCardData[];

  async function resetAi(clearPaper: boolean) {
    const ok = await confirm({
      title: clearPaper ? "AI paper alımları temizlensin mi?" : "AI istatistikleri sıfırlansın mı?",
      body: clearPaper
        ? "Bu işlem AI_TRADE paper alım/satım kayıtlarını siler, açık AI paper pozisyonlarını temizler ve yeni ölçüm dönemini başlatır. Canlı işlemlere ve gerçek cüzdana dokunmaz."
        : "Bu işlem eski kayıtları silmez; AI Decision Center bundan sonrasını yeni dönem olarak sayar. Geçmiş teknik loglar saklanır.",
      confirmText: clearPaper ? "Temizle" : "Sıfırla",
      danger: clearPaper,
    });
    if (!ok) return;
    try {
      const res = await apiSend<any>(`/trading/reset-stats?scope=ai&clear_paper=${clearPaper ? "true" : "false"}`, "POST");
      toast("success", clearPaper ? `${res.deleted_paper_rows || 0} AI paper kaydı temizlendi` : "AI ölçüm dönemi sıfırlandı");
      await mutateResetStatus();
      await mutateCenter();
    } catch (e: any) {
      toast("error", e?.message || "Sıfırlama yapılamadı");
    }
  }

  return (
    <div className="space-y-5">
      {dialog}
      <DecisionDrawer open={!!selected} item={selected} mode="ai" onClose={() => setSelected(null)} />
      <PageHeader
        title="AI Decision Center"
        subtitle="AI Trade’in gördüğü tokenları, neden aldığını, neden almadığını, nerede çıktığını ve paper performansını tek ekranda gösterir."
        action={<Link className="btn" href="/settings/risk">AI ayarları <ArrowRight size={15} /></Link>}
      />

      <div className="ai-command-card">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-2xl font-black"><BrainCircuit className="brand" /> AI Trade Karar Merkezi</div>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed muted">
              Bu ekran teknik logların özeti değil; AI motorunun karar defteri. Hangi tokenı fırsat gördü, hangi sinyali eledi, paper’da nereden girdi ve hangi çıkış kuralıyla kapattı burada okunur.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 xl:min-w-[520px]">
            <div className="mini-kpi"><span>Aktif mod</span><b>{activeAi ? "AI TRADE" : "AI pasif"}</b></div>
            <div className="mini-kpi"><span>İşlem modu</span><b>{r.mode || "paper"}</b></div>
            <div className="mini-kpi"><span>Risk iştahı</span><b>{profileLabel(r.ai_risk_profile)}</b></div>
            <div className="mini-kpi"><span>AI canlı kilidi</span><b>{r.ai_live_enabled ? "Açık" : "Kilitli"}</b></div>
          </div>
        </div>
      </div>

      {!activeAi && (
        <Callout kind="warn">
          Şu an Copy Trade modu aktif. AI Decision Center veri gösterebilir ama AI token motoru yeni işlem üretmez. AI panelini test etmek için ana sayfadan AI TRADE seç.
        </Callout>
      )}
      {!paperMode && (
        <Callout kind="warn">
          AI canlı moddan önce paper tarafında yeterli örnek görmek daha sağlıklı. Bu ekran paper performansını referans alır; canlı PnL gerçek cüzdanla ayrıca doğrulanmalı.
        </Callout>
      )}

      <section className="card reset-zone">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 font-extrabold">
              <RotateCcw size={17} className="brand" /> Temiz ölçüm dönemi
              <InfoTip title="İstatistik ve alım sıfırlama">Güncellemelerden önceki paper sonuçları kar/zararı karıştırıyorsa yeni dönem başlat. İstatistik sıfırlama kayıt silmez; paper alımları temizleme ise AI_TRADE paper kayıtlarını siler. Canlı işlemlere dokunmaz.</InfoTip>
            </div>
            <div className="mt-1 text-xs muted">
              Başlangıç: {resetStatus?.baseline_at ? new Date(resetStatus.baseline_at).toLocaleString("tr-TR") : "Henüz sıfırlanmadı"}
              {resetStatus?.since_counts && <> · Yeni dönem alım: <b>{resetStatus.since_counts.buys}</b> · PnL: <b>{sol(resetStatus.since_counts.realized_pnl_sol)}</b></>}
            </div>
          </div>
          <Link href="/history#reset" className="btn"><RotateCcw size={15} /> Sıfırlama Merkezi</Link>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatCard label="Karar" value={fmtNum(s.decisions || 0, 0)} hint={`${minutes} dk pencere`} icon={<BrainCircuit size={18} />} tone="var(--violet)" />
        <StatCard label="Alım" value={fmtNum(s.opened_decisions || 0, 0)} hint="AI açtı" icon={<Zap size={18} />} tone="var(--emerald)" />
        <StatCard label="Almadı" value={fmtNum(s.blocked_decisions || 0, 0)} hint="Filtreledi" icon={<FilterX size={18} />} tone="var(--amber)" />
        <StatCard label="Paper PnL" value={sol(s.realized_pnl_sol)} hint="Kapanan AI" icon={<LineChart size={18} />} tone={(s.realized_pnl_sol || 0) >= 0 ? "var(--emerald)" : "var(--rose)"} />
        <StatCard label="Win Rate" value={pct(s.win_rate)} hint={`${s.closed_trades || 0} kapalı`} icon={<TrendingUp size={18} />} tone="var(--sky)" />
        <StatCard label="Açık" value={fmtNum(s.open_positions || 0, 0)} hint={sol(s.open_exposure_sol)} icon={<Wallet size={18} />} tone="var(--brand)" />
        <StatCard label="Ort. Hold" value={s.avg_hold_minutes ? `${fmtNum(s.avg_hold_minutes, 1)} dk` : "—"} hint="Kapanan işlem" icon={<TimerReset size={18} />} tone="var(--violet)" />
        <StatCard label="En kötü" value={sol(s.worst_pnl_sol)} hint="Risk kontrol" icon={<TrendingDown size={18} />} tone="var(--rose)" />
      </div>

      {center?.report && (
        <section className="card" style={{ borderColor: center.report.live_ready ? "color-mix(in srgb, var(--emerald) 45%, var(--border))" : "var(--border)" }}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-bold"><FlaskConical size={18} className="brand" /> AI Paper Karnesi
              <InfoTip title="AI Paper Karnesi">Kapanan paper işlemlerden hesaplanır: örneklem, PnL, kenar (isabet/profit factor) ve kuyruk riski. Dört kriter de yeşilse canlıya küçük bakiyeyle geçmek makuldür.</InfoTip>
            </h2>
            <div className="flex items-center gap-2">
              <span className="grid h-10 w-10 place-items-center rounded-2xl text-lg font-black text-white"
                style={{ background: center.report.grade === "A" ? "var(--emerald)" : center.report.grade === "B" ? "var(--sky)" : center.report.grade === "C" ? "var(--amber)" : "var(--rose)" }}>
                {center.report.grade}
              </span>
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${center.report.live_ready ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>
                {center.report.live_ready ? "CANLIYA HAZIR" : "PAPER'DA KAL"}
              </span>
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(center.report.criteria || []).map((c: any) => (
              <div key={c.key} className="flex items-center justify-between rounded-xl border px-3 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
                <span className="flex items-center gap-2">
                  {c.ok ? <CheckCircle2 size={15} className="text-emerald-500" /> : <XCircle size={15} className="text-amber-500" />}
                  {c.label}
                </span>
                <b className="text-xs muted">{String(c.value)}</b>
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-xs muted">
            <span>Profit factor: <b>{center.report.profit_factor}</b></span>
            <span>Medyan hold: <b>{center.report.median_hold_minutes ?? "—"} dk</b></span>
            <span className="font-semibold" style={{ color: center.report.live_ready ? "var(--emerald)" : "var(--amber)" }}>{center.report.verdict}</span>
          </div>
        </section>
      )}

      {tradeCards.length > 0 && (
        <section className="card">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 font-bold"><Sparkles size={18} className="brand" /> Tamamlanan İşlem Kartları
              <InfoTip title="İşlem kartları">Kapanan her AI işlemi otomatik olarak paylaşılabilir bir banner'a dönüşür. En son işlemin kartı üstte; "Tümünü gör" ile sırayla hepsi açılır. Her kart PNG indirilebilir.</InfoTip>
            </h2>
            <button className="btn" onClick={() => setShowAllCards((v) => !v)}>
              {showAllCards ? "Gizle" : `Tümünü gör (${tradeCards.length})`}
            </button>
          </div>
          {!showAllCards ? (
            <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr] lg:items-center">
              <TradeShareCard data={tradeCards[0]} />
              <div className="flex flex-col gap-2">
                <div className="text-sm muted">En son kapanan AI işlemi. Otomatik oluşturuldu.</div>
                <button className="btn-primary w-fit"
                  onClick={() => downloadTradeCardPng(tradeCards[0], `${tradeCards[0].symbol}-${tradeCards[0].pnlPct >= 0 ? "kar" : "zarar"}.png`)}>
                  <Download size={15} /> PNG indir
                </button>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {tradeCards.map((c, i) => (
                <div key={`${c.symbol}-${c.when || i}`} className="flex flex-col gap-2">
                  <TradeShareCard data={c} />
                  <button className="btn-ghost w-fit"
                    onClick={() => downloadTradeCardPng(c, `${c.symbol}-${c.pnlPct >= 0 ? "kar" : "zarar"}.png`)}>
                    <Download size={13} /> PNG
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.15fr_.85fr]">
        <PremiumBarChart data={reasons} label="AI Karar Hunisi — Görsel" />
        <PremiumDonut data={exitDonut} label="Exit Sebepleri — Görsel" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <section className="card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-bold flex items-center gap-2"><Sparkles size={18} className="brand" /> AI öneri ve teşhis</h2>
            <InfoTip title="AI öneri ve teşhis">Bu kutu son paper sonuçları ve karar hunisine göre AI’ın çok katı mı, çok gevşek mi olduğunu söyler. Canlıya geçmeden önce burası özellikle takip edilmeli.</InfoTip>
          </div>
          <div className="space-y-2">
            {recs.map((r: any, i: number) => (
              <div key={`${r.title}-${i}`} className="rounded-2xl border p-3" style={{ borderColor: `${recommendationTone(r.level)}66`, background: "color-mix(in srgb, var(--bg2) 48%, transparent)" }}>
                <div className="text-sm font-extrabold" style={{ color: recommendationTone(r.level) }}>{r.title}</div>
                <div className="mt-1 text-xs leading-relaxed muted">{r.text}</div>
              </div>
            ))}
            {recs.length === 0 && <div className="rounded-2xl border border-dashed p-6 text-center text-xs muted">Henüz öneri için yeterli veri yok.</div>}
          </div>
        </section>

        <section className="card">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="font-bold flex items-center gap-2"><FilterX size={18} className="brand" /> Neden Almadım? Hunisi</h2>
            <div className="flex gap-1 rounded-xl border p-1" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>
              {([15, 60, 240, 1440] as WindowMinutes[]).map((m) => (
                <button key={m} className={minutes === m ? "mode-pill active" : "mode-pill"} onClick={() => setMinutes(m)}>{m === 1440 ? "24s" : `${m}dk`}</button>
              ))}
            </div>
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
            <div className="mini-kpi"><span>Toplam</span><b>{fmtNum(s.decisions || 0, 0)}</b></div>
            <div className="mini-kpi"><span>Aldı</span><b>{fmtNum(s.opened_decisions || 0, 0)}</b></div>
            <div className="mini-kpi"><span>Almadı</span><b>{fmtNum(s.blocked_decisions || 0, 0)}</b></div>
          </div>
          <div className="space-y-2">
            {reasons.slice(0, 9).map((x: any) => (
              <div key={x.reason} className="reason-row">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="line-clamp-1 muted">{x.reason}</span>
                  <b>{x.count}</b>
                </div>
                <div className="reason-meter"><span style={{ width: `${Math.min(100, Number(x.pct || 0) * 100)}%` }} /></div>
              </div>
            ))}
            {reasons.length === 0 && <div className="rounded-2xl border border-dashed p-8 text-center text-xs muted">Henüz huni verisi yok. Listener açıkken AI sinyalleri geldikçe dolar.</div>}
          </div>
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_.65fr]">
        <section className="card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-bold flex items-center gap-2"><FlaskConical size={18} className="brand" /> AI Paper Performans Analizi</h2>
            <InfoTip title="AI Paper Performans Analizi">Her kart bir token denemesidir. Giriş nedeni, çıkış nedeni, tutma süresi, PnL ve açık/kapalı durumu birlikte görünür.</InfoTip>
          </div>
          {sessions.length === 0 ? (
            <PremiumEmpty title="Henüz AI paper işlemi yok" text="AI TRADE aktif, motor açık ve token akışı çalışıyorsa burada token denemeleri kart olarak oluşur." />
          ) : (
            <div className="space-y-3">
              {sessions.slice(0, 14).map((t: any) => {
                const positive = Number(t.pnl_sol || 0) >= 0;
                const open = t.status === "open";
                return (
                  <div key={`${t.token_mint}-${t.entry_time || t.exit_time}`} className="decision-card cursor-pointer card-hover" onClick={() => setSelected(t)}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <Link href={`/tokens/${t.token_mint}`} className="text-base font-extrabold clickable">{t.token?.symbol || shortAddr(t.token_mint)}</Link>
                          <span className="text-xs muted">{shortAddr(t.token_mint)}</span>
                        </div>
                        <div className="mt-1 text-xs muted">Giriş: {t.entry_time ? new Date(t.entry_time).toLocaleString("tr-TR") : "—"}</div>
                      </div>
                      <span className={open ? "status-pill warn" : positive ? "status-pill good" : "status-pill bad"}>{open ? "Açık" : positive ? "Kâr" : "Zarar"}</span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
                      <div className="mini-kpi"><span>Giriş</span><b>{sol(t.cost_sol)}</b></div>
                      <div className="mini-kpi"><span>Çıkış</span><b>{t.exit_time ? sol(t.proceeds_sol) : "—"}</b></div>
                      <div className="mini-kpi"><span>PnL</span><b className={positive ? "text-emerald-500" : "text-red-500"}>{sol(t.pnl_sol)}</b></div>
                      <div className="mini-kpi"><span>Hold</span><b>{t.hold_minutes !== null && t.hold_minutes !== undefined ? `${fmtNum(t.hold_minutes, 1)} dk` : open ? "Açık" : "—"}</b></div>
                      <div className="mini-kpi"><span>Çıkış sebebi</span><b>{t.exit_reason || (open ? "Bekliyor" : "—")}</b></div>
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      <div className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>
                        <b>Neden aldı?</b>
                        <p className="mt-1 leading-relaxed muted">{t.entry_reason || "AI uygun gördü"}</p>
                      </div>
                      <div className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>
                        <b>Nerede çıktı?</b>
                        <p className="mt-1 leading-relaxed muted">{open ? "Pozisyon hâlâ açık; TP/SL/trailing/max hold bekleniyor." : `${t.exit_reason || "Çıkış"} · çıkış fiyatı ${t.exit_price_sol ? fmtNum(t.exit_price_sol, 10) : "—"} SOL`}</p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-bold flex items-center gap-2"><ShieldCheck size={18} className="brand" /> Exit Sebebi Takibi</h2>
            <InfoTip title="Exit Sebebi Takibi">AI lider takip etmediği için çıkış kalitesi TP/SL/trailing/max hold ile ölçülür. Zararların çoğu SL ise giriş zayıf; çoğu zaman çıkışı ise token çok geç seçiliyor olabilir.</InfoTip>
          </div>
          <div className="space-y-2">
            {exits.map((x: any) => {
              const tone = exitTone(x.reason);
              return (
                <div key={x.reason} className="flex items-center justify-between rounded-2xl border px-3 py-3 text-sm"
                  style={{ borderColor: `color-mix(in srgb, ${tone} 40%, var(--border))`, background: `color-mix(in srgb, ${tone} 8%, var(--bg2))` }}>
                  <span className="flex items-center gap-2 font-semibold">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: tone }} />
                    <span style={{ color: tone }}>{x.reason}</span>
                  </span>
                  <b className="font-mono tabular-nums" style={{ color: tone }}>{x.count}</b>
                </div>
              );
            })}
            {exits.length === 0 && <div className="rounded-2xl border border-dashed p-8 text-center text-xs muted">Henüz kapanan AI pozisyonu yok.</div>}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-bold flex items-center gap-2"><Gauge size={18} className="brand" /> AI Karar Akışı</h2>
          <InfoTip title="AI Karar Akışı">Logların sadeleştirilmiş halidir. Burada önemli alım, almama ve çıkış kararları zaman sırasıyla görünür.</InfoTip>
        </div>
        {feed.length === 0 ? (
          <PremiumEmpty title="Henüz AI karar kaydı yok" text="Listener token akışı aldıkça AI burada neden almadığını veya neden işlem açtığını gösterecek." />
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {feed.slice(0, 24).map((d: any) => (
              <div key={d.id} className="decision-log-row cursor-pointer card-hover" onClick={() => setSelected(d)}>
                <div className="mt-0.5">{actionIcon(d.action)}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-semibold">{d.action === "opened" ? "AI işlem açtı" : d.action === "blocked" ? "AI almadı" : d.action === "exit" ? "AI çıkış yaptı" : "AI bilgi"}</div>
                    <div className="text-[11px] muted">{new Date(d.created_at).toLocaleString("tr-TR")}</div>
                  </div>
                  <div className="mt-0.5 text-xs muted line-clamp-2">{d.reason || d.message}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-[11px] muted">
                    {d.token && <Link href={`/tokens/${d.token}`} className="clickable">{shortAddr(d.token)}</Link>}
                    {d.token_score !== undefined && d.token_score !== null && <span>Skor {fmtNum(d.token_score, 0)}</span>}
                    {d.early_quality != null && (() => {
                      const q = Number(d.early_quality);
                      const c = q >= 55 ? "var(--emerald)" : q >= 40 ? "var(--amber)" : "var(--rose)";
                      return (
                        <span className="rounded px-1.5 py-0.5 font-mono tabular-nums"
                          style={{ color: c, background: `color-mix(in srgb, ${c} 14%, transparent)` }}>
                          Erken kalite {fmtNum(q, 0)}
                        </span>
                      );
                    })()}
                    {d.tape && (
                      <span className="font-mono tabular-nums">
                        {d.tape.unique_buyers != null ? `${d.tape.unique_buyers} alıcı` : ""}
                        {d.tape.top_buyer_share != null ? ` · tek cüzdan %${Math.round(Number(d.tape.top_buyer_share) * 100)}` : ""}
                        {d.tape.buy_sell_ratio != null ? ` · al/sat ${d.tape.buy_sell_ratio}` : ""}
                      </span>
                    )}
                    {d.pnl_sol !== undefined && d.pnl_sol !== null && <span>PnL {sol(d.pnl_sol)}</span>}
                    {d.bucket && <span>{d.bucket}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <Callout kind="info">
        <b>Sıradaki okuma şekli:</b> AI canlıya geçmeden önce bu ekranda en az 24 saat paper verisi biriktir. Kâr/zarar kadar “neden almadı” ve “hangi exit sebebi zarar yazdırıyor” bölümleri de kararın ana parçası olmalı.
      </Callout>
    </div>
  );
}

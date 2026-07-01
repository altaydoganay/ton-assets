"use client";
import useSWR from "swr";
import { RefreshCw, ShieldCheck, TimerReset, RotateCcw, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { TradeTable } from "@/components/TradeTable";
import { Callout, InfoTip, StatCard } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { apiSend, fetcher, fmtNum } from "@/lib/api";
import { useToast } from "@/components/Toast";

export default function Paper() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const { data: exitStatus, mutate, isLoading } = useSWR<any>("/trading/ai-exit/status", fetcher, { refreshInterval: 5000 });
  const { data: resetStatus, mutate: mutateResetStatus } = useSWR<any>("/trading/reset-status?scope=all", fetcher, { refreshInterval: 10000 });
  const openAi = Number(exitStatus?.open_ai_paper_positions || 0);
  const oldest = Number(exitStatus?.oldest_age_minutes || 0);
  const maxHold = Number(exitStatus?.max_hold_minutes || 0);
  const overdue = maxHold > 0 && oldest >= maxHold;

  async function runExit() {
    try {
      const res = await apiSend<any>("/trading/ai-exit/run", "POST");
      toast("success", `AI çıkış kontrolü çalıştı: ${res.closed || 0} pozisyon kapandı`);
      await mutate();
    } catch (e: any) {
      toast("error", e?.message || "AI çıkış kontrolü çalışmadı");
    }
  }

  async function resetPaper(clearPaper: boolean) {
    const ok = await confirm({
      title: clearPaper ? "Tüm paper alım/satım kayıtları temizlensin mi?" : "Paper istatistikleri sıfırlansın mı?",
      body: clearPaper
        ? "Bu işlem tüm paper alım/satım kayıtlarını siler ve paper motorunu temiz başlatır. Canlı işlem kayıtlarına ve gerçek cüzdana dokunmaz."
        : "Bu işlem kayıtları silmez; raporlar için yeni ölçüm dönemi başlatır.",
      confirmText: clearPaper ? "Tümünü temizle" : "Sıfırla",
      danger: clearPaper,
    });
    if (!ok) return;
    try {
      const res = await apiSend<any>(`/trading/reset-stats?scope=all&clear_paper=${clearPaper ? "true" : "false"}`, "POST");
      toast("success", clearPaper ? `${res.deleted_paper_rows || 0} paper kaydı temizlendi` : "Paper ölçüm dönemi sıfırlandı");
      await mutateResetStatus();
      await mutate();
    } catch (e: any) {
      toast("error", e?.message || "Sıfırlama yapılamadı");
    }
  }

  return (
    <div className="space-y-5">
      {dialog}
      <PageHeader
        title="Paper Trading"
        subtitle="Gerçek para kullanmadan simüle edilen işlemler. AI modunda açık pozisyonları TP / SL / trailing / max-hold yöneticisi kapatır."
        action={<button className="btn" onClick={runExit}><RefreshCw size={15} /> AI çıkışı kontrol et</button>}
      />

      <section className="card reset-zone">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 font-extrabold">
              <RotateCcw size={17} className="brand" /> Paper ölçüm sıfırlama
              <InfoTip title="Paper sıfırlama">İstatistik sıfırlama geçmişi silmeden yeni dönem başlatır. Paper kayıtlarını temizleme ise tüm simülasyon alım/satımlarını siler; canlı işlemlere dokunmaz.</InfoTip>
            </div>
            <div className="mt-1 text-xs muted">
              Başlangıç: {resetStatus?.baseline_at ? new Date(resetStatus.baseline_at).toLocaleString("tr-TR") : "Henüz sıfırlanmadı"}
              {resetStatus?.since_counts && <> · Yeni dönem alım: <b>{resetStatus.since_counts.buys}</b> · PnL: <b>{resetStatus.since_counts.realized_pnl_sol} SOL</b></>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => resetPaper(false)}><RotateCcw size={15} /> İstatistiği sıfırla</button>
            <button className="btn-danger" onClick={() => resetPaper(true)}><Trash2 size={15} /> Paper alımları temizle</button>
          </div>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-4">
        <StatCard label="AI açık paper" value={fmtNum(openAi, 0)} hint="AI_TRADE pozisyonu" icon={<ShieldCheck size={18} />} tone="var(--violet)" />
        <StatCard label="En eski AI pozisyon" value={`${fmtNum(oldest, 1)} dk`} hint="İlk buy zamanına göre" icon={<TimerReset size={18} />} tone={overdue ? "var(--rose)" : "var(--sky)"} />
        <StatCard label="Max hold" value={`${fmtNum(maxHold, 0)} dk`} hint="Bu süre dolunca kapatır" icon={<TimerReset size={18} />} tone="var(--brand)" />
        <StatCard label="AI çıkış yöneticisi" value={exitStatus?.enabled ? "Aktif" : "Pasif"} hint={exitStatus?.strategy_mode === "ai" ? "AI modunda" : "Copy modu"} icon={<ShieldCheck size={18} />} tone={exitStatus?.enabled ? "var(--emerald)" : "var(--amber)"} />
      </div>

      {overdue && (
        <Callout kind="warn">
          Bazı AI paper pozisyonları max-hold süresini geçmiş görünüyor. Normalde arka plan yöneticisi kapatmalı. “AI çıkışı kontrol et” butonu manuel olarak aynı çıkış kontrolünü çalıştırır.
        </Callout>
      )}
      {!isLoading && exitStatus?.last_exit_log && (
        <Callout kind="info">
          Son çıkış: {exitStatus.last_exit_log.message}
        </Callout>
      )}

      <TradeTable path="/trading/paper" emptyLabel="Henüz paper işlem yok" />
    </div>
  );
}

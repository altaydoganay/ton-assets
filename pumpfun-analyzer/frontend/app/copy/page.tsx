"use client";
import Link from "next/link";
import useSWR from "swr";
import { CopyCheck, Trophy, Wallet, FlaskConical, ShieldCheck, ArrowRight, CheckCircle2, XCircle, Clock, LineChart as LineChartIcon, RotateCcw, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { StatCard, InfoTip, Callout } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { DecisionDrawer, PremiumDonut, PremiumLineChart, PremiumEmpty } from "@/components/PremiumUI";
import { useState } from "react";
import { apiSend, fetcher, fmtNum, shortAddr } from "@/lib/api";

function isCopyTrade(t: any) { return t.wallet_address !== "AI_TRADE" && !String(t.reason || "").startsWith("ai-"); }

export default function CopyTradePage() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 15000 });
  const { data: paper, mutate: mutatePaper } = useSWR<any[]>("/trading/paper?limit=500", fetcher, { refreshInterval: 10000 });
  const { data: resetStatus, mutate: mutateResetStatus } = useSWR<any>("/trading/reset-status?scope=copy", fetcher, { refreshInterval: 10000 });
  const { data: decisions } = useSWR<any[]>("/trading/decisions?strategy=copy&limit=80", fetcher, { refreshInterval: 8000 });
  const [selected, setSelected] = useState<any>(null);
  const baseline = resetStatus?.baseline_at ? new Date(resetStatus.baseline_at).getTime() : 0;
  const copyRows = (paper || [])
    .filter(isCopyTrade)
    .filter((t) => !baseline || new Date(t.created_at).getTime() >= baseline);
  const buys = copyRows.filter((t) => t.side === "buy").length;
  const sells = copyRows.filter((t) => t.side === "sell");
  const pnl = sells.reduce((s, t) => s + Number(t.realized_pnl_sol || 0), 0);
  const wins = sells.filter((t) => Number(t.realized_pnl_sol || 0) > 0).length;
  const winRate = sells.length ? wins / sells.length : 0;

  async function resetCopy(clearPaper: boolean) {
    const ok = await confirm({
      title: clearPaper ? "Copy paper alımları temizlensin mi?" : "Copy istatistikleri sıfırlansın mı?",
      body: clearPaper
        ? "Bu işlem AI dışı copy paper alım/satım kayıtlarını siler ve copy ölçümünü temiz başlatır. Canlı işlemlere ve gerçek cüzdana dokunmaz."
        : "Bu işlem kayıt silmez; Copy paneli bundan sonrasını yeni dönem olarak sayar.",
      confirmText: clearPaper ? "Temizle" : "Sıfırla",
      danger: clearPaper,
    });
    if (!ok) return;
    try {
      const res = await apiSend<any>(`/trading/reset-stats?scope=copy&clear_paper=${clearPaper ? "true" : "false"}`, "POST");
      toast("success", clearPaper ? `${res.deleted_paper_rows || 0} copy paper kaydı temizlendi` : "Copy ölçüm dönemi sıfırlandı");
      await mutatePaper();
      await mutateResetStatus();
    } catch (e: any) {
      toast("error", e?.message || "Sıfırlama yapılamadı");
    }
  }

  return (
    <div className="space-y-5">
      {dialog}
      <DecisionDrawer open={!!selected} item={selected} mode="copy" onClose={() => setSelected(null)} />
      <PageHeader
        title="Copy Trade Paneli"
        subtitle="Cüzdan bazlı sistemin sade kontrol ekranı: takip listesi, copy sonucu, lider-watch ve son kararlar."
        action={<Link className="btn" href="/wallets/leaderboard">Cüzdan sıralaması <ArrowRight size={15} /></Link>}
      />

      <div className="copy-command-card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-2xl font-black"><CopyCheck className="text-emerald-500" /> Copy Trade aktif ekranı</div>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed muted">
              Burada sadece copy sistemini ilgilendiren metrikler var. AI token kararları bu ekranda gösterilmez; cüzdan kalitesi, copy PnL ve takip listesi önemlidir.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:min-w-[440px]">
            <div className="mini-kpi"><span>Takipte</span><b>{fmtNum(ov?.wallets?.tracked || 0, 0)}</b></div>
            <div className="mini-kpi"><span>Toplam cüzdan</span><b>{fmtNum(ov?.wallets?.total || 0, 0)}</b></div>
            <div className="mini-kpi"><span>Paper kapanış</span><b>{fmtNum(sells.length, 0)}</b></div>
            <div className="mini-kpi"><span>Win rate</span><b>%{fmtNum(winRate * 100, 0)}</b></div>
          </div>
        </div>
      </div>

      <section className="card reset-zone">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 font-extrabold"><RotateCcw size={17} className="text-emerald-500" /> Copy temiz ölçüm dönemi <InfoTip title="Copy sıfırlama">Güncellemelerden önceki copy paper sonuçları karıştıysa yeni dönem başlat. İstatistik sıfırlama silmez, paper temizleme AI dışı copy simülasyon kayıtlarını siler.</InfoTip></div>
            <div className="mt-1 text-xs muted">Başlangıç: {resetStatus?.baseline_at ? new Date(resetStatus.baseline_at).toLocaleString("tr-TR") : "Henüz sıfırlanmadı"}{resetStatus?.since_counts && <> · Yeni dönem alım: <b>{resetStatus.since_counts.buys}</b> · PnL: <b>{fmtNum(resetStatus.since_counts.realized_pnl_sol, 4)} SOL</b></>}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => resetCopy(false)}><RotateCcw size={15} /> İstatistiği sıfırla</button>
            <button className="btn-danger" onClick={() => resetCopy(true)}><Trash2 size={15} /> Copy paper temizle</button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <StatCard label="Copy Paper PnL" value={`${fmtNum(pnl, 4)} SOL`} hint="AI dışı copy işlemleri" icon={<FlaskConical size={18} />} tone={pnl >= 0 ? "var(--emerald)" : "var(--rose)"} />
        <StatCard label="Takip Cüzdanı" value={fmtNum(ov?.wallets?.tracked || 0, 0)} hint="Canlı/copy adayları" icon={<Wallet size={18} />} tone="var(--emerald)" />
        <StatCard label="Elite Havuz" value={fmtNum(ov?.wallets?.analyzed || 0, 0)} hint="Analiz edilmiş" icon={<Trophy size={18} />} tone="var(--violet)" />
        <StatCard label="Genel Paper PnL" value={`${fmtNum(perf?.total_pnl_sol || 0, 4)} SOL`} hint="Tüm paper sonucu" icon={<ShieldCheck size={18} />} tone="var(--sky)" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
        <PremiumLineChart data={perf?.curve || []} label="Copy / Paper Equity" />
        <PremiumDonut data={[{ name: "Kazanç", value: wins }, { name: "Zarar", value: Math.max(0, sells.length - wins) }]} label="Copy Win / Loss" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_.9fr]">
        <section className="card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-bold">Son copy işlemleri</h2>
            <InfoTip title="Son copy işlemleri">Takip cüzdanı kaynaklı paper işlemlerdir. AI Trade alımları burada ayrıştırılmaz.</InfoTip>
          </div>
          {copyRows.slice(0, 12).length === 0 ? (
            <PremiumEmpty title="Henüz copy paper işlemi yok" text="Copy mod aktif, takip listesi hazır ve motor açık olduğunda burada lider kaynaklı paper işlemler görünecek." />
          ) : (
            <div className="space-y-2">
              {copyRows.slice(0, 12).map((t) => (
                <div key={t.id} className="decision-log-row cursor-pointer card-hover" onClick={() => setSelected(t)}>
                  <div>{t.side === "buy" ? <CheckCircle2 size={16} className="text-emerald-500" /> : <XCircle size={16} className={Number(t.realized_pnl_sol || 0) >= 0 ? "text-emerald-500" : "text-red-500"} />}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                      <span>{t.side === "buy" ? "Copy alım" : "Copy satış"}</span>
                      <Link href={`/tokens/${t.token_mint}`} className="clickable">{shortAddr(t.token_mint)}</Link>
                    </div>
                    <div className="mt-1 text-xs muted">{new Date(t.created_at).toLocaleString("tr-TR")} · {fmtNum(t.sol_amount, 4)} SOL · PnL {fmtNum(t.realized_pnl_sol, 4)} SOL</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-bold">Copy kararları</h2>
            <InfoTip title="Copy kararları">İşlem açıldı mı, açılmadıysa hangi güvenlik/risk sebebiyle açılmadı burada sade görünür.</InfoTip>
          </div>
          {(decisions || []).length === 0 ? <div className="rounded-2xl border border-dashed p-8 text-center muted">Karar kaydı yok.</div> : (
            <div className="space-y-2">
              {(decisions || []).slice(0, 14).map((d) => {
                const ok = d.action === "buy" || d.action === "opened" || String(d.message || "").includes("İşlem AÇILDI");
                return (
                  <div key={d.id} className="decision-log-row cursor-pointer card-hover" onClick={() => setSelected(d)}>
                    <div className="mt-0.5">{ok ? <CheckCircle2 size={16} className="text-emerald-500" /> : <Clock size={16} className="text-amber-400" />}</div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold">{ok ? "Copy işlem açtı" : "Copy işlem açmadı"}</div>
                      <div className="mt-0.5 text-xs muted line-clamp-2">{d.reason || d.message}</div>
                      <div className="mt-1 text-[11px] muted">{new Date(d.created_at).toLocaleString("tr-TR")} {d.token ? `· ${shortAddr(d.token)}` : ""}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      <Callout kind="info">
        <b>Copy için ana gelişim alanı:</b> cüzdan sayısını artırmak değil, live alım yetkisi olan cüzdanları azaltmak. Copyability, bağımsızlık ve leader-watch copy sisteminin ana güvenlik üçlüsü olmalı.
      </Callout>
    </div>
  );
}

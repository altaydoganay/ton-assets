"use client";
import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, shortAddr, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section } from "@/components/ui";
import { Loading } from "@/components/States";
import { useToast } from "@/components/Toast";
import { CountUp } from "@/components/CountUp";
import { Trophy, ArrowUpDown, ArrowUp, ArrowDown, RefreshCw, Crown, Medal, Award } from "lucide-react";

type Row = Record<string, any>;

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)} sn önce`;
  if (s < 3600) return `${Math.round(s / 60)} dk önce`;
  return `${Math.round(s / 3600)} sa önce`;
}

const COLS: { key: string; label: string; fmt?: (v: any, r?: Row) => string; right?: boolean }[] = [
  { key: "score", label: "Puan", fmt: (v) => (v != null ? Math.round(v).toString() : "—") },
  { key: "win_rate", label: "Başarı", fmt: (v) => (v != null ? `%${Math.round(v * 100)}` : "—") },
  { key: "realized_pnl_sol", label: "Lider PnL (SOL)", right: true, fmt: (v) => (v != null ? Number(v).toFixed(3) : "—") },
  { key: "profit_factor", label: "Profit Factor", fmt: (v) => (v != null ? Number(v).toFixed(2) : "∞/—") },
  { key: "closed_positions", label: "Kapalı İşlem", fmt: (v) => v ?? "—" },
  { key: "token_diversity", label: "Token Çeşit.", fmt: (v) => v ?? "—" },
  { key: "avg_buy_size_sol", label: "Ort. Alım ◎", fmt: (v) => (v != null ? Number(v).toFixed(3) : "—") },
  { key: "history_days", label: "Geçmiş (gün)", fmt: (v) => (v != null ? Math.round(v).toString() : "—") },
];

export default function Leaderboard() {
  const { data, mutate } = useSWR<Row[]>("/wallets/leaderboard", fetcher, { refreshInterval: 30000 });
  const { data: backlog, mutate: mutBacklog } = useSWR<any>("/setup/backlog", fetcher, { refreshInterval: 15000 });
  const [sortKey, setSortKey] = useState("score");
  const [dir, setDir] = useState<1 | -1>(-1);
  const [scanning, setScanning] = useState(false);
  const [draining, setDraining] = useState(false);
  const toast = useToast();
  const drain = backlog?.last_drain;
  const autoOn = !!backlog?.autodrain;
  const isRunning = !!drain?.running;
  const [autoBusy, setAutoBusy] = useState(false);

  async function toggleAuto(next: boolean) {
    setAutoBusy(true);
    try {
      await apiSend(`/setup/backlog/autodrain?enabled=${next}`, "POST");
      await mutBacklog();
      toast(next ? "success" : "info",
        next ? "Otomatik analiz açıldı — backlog arka planda erimeye başlayacak (~1-2 dk içinde hareket görünür)."
             : "Otomatik analiz durduruldu.");
    } catch (e: any) { toast("error", e?.message || "Değiştirilemedi"); }
    finally { setAutoBusy(false); }
  }
  // Çalışırken backlog'u sık güncelle (canlı ilerleme)
  useEffect(() => {
    if (!isRunning && !autoOn) return;
    const id = setInterval(() => { mutBacklog(); mutate(); }, 5000);
    return () => clearInterval(id);
  }, [isRunning, autoOn, mutBacklog, mutate]);
  // tek-seferlik manuel burst bitince bildirim göster
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && drain && !drain.running && !autoOn) {
      toast("success",
        `Analiz turu bitti: +${drain.processed} işlendi · +${drain.tracked} takibe · ${Number(drain.remaining ?? 0).toLocaleString("tr-TR")} kaldı`);
      mutate();
    }
    wasRunning.current = !!drain?.running;
  }, [drain, autoOn, toast, mutate]);

  async function rescan() {
    setScanning(true);
    try {
      const r: any = await apiSend("/wallets/rescan", "POST");
      await mutate();
      const promoted = r.to_tracked ?? 0;
      const noData = r.skipped_no_data ?? 0;
      const remain = r.remaining ? ` · ${r.remaining} kaldı (tekrar çalıştır)` : "";
      const hint = noData > 0 ? ` · ${noData} cüzdanın verisi yok → aşağıdan "Backlog Analizi" gerekir` : "";
      toast(promoted > 0 ? "success" : "info",
        `Tarandı: ${r.scanned ?? 0} cüzdan · +${promoted} yeni takibe alındı ` +
        `(toplam takip: ${r.after_tracked ?? "?"})${remain}${hint}`);
    } catch (e: any) {
      toast("error", e?.message || "Yeniden tarama başarısız");
    } finally { setScanning(false); }
  }

  async function drainBacklog(count: number) {
    setDraining(true);
    try {
      const r: any = await apiSend(`/setup/backlog/analyze?count=${count}`, "POST");
      await mutBacklog();
      if (r.started) toast("success", `${r.target} cüzdanın analizi başladı (~${r.est_credits} kredi). İlerleme aşağıda güncellenecek.`);
      else toast("info", r.message || "Backlog boş");
    } catch (e: any) {
      toast("error", e?.message || "Backlog analizi başlatılamadı");
    } finally { setDraining(false); }
  }

  if (!data) return <Loading />;

  const rows = [...data].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity, bv = b[sortKey] ?? -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });
  // Podyum: en çok KAZANDIRAN ilk 3 (sıralamadan bağımsız)
  const podium = [...data]
    .filter((w) => (w.closed_trades ?? 0) > 0)
    .sort((a, b) => (b.realized_pnl_sol ?? -Infinity) - (a.realized_pnl_sol ?? -Infinity))
    .slice(0, 3);
  function sortBy(k: string) {
    if (k === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(k); setDir(-1); }
  }
  const SortIco = ({ k }: { k: string }) => k !== sortKey
    ? <ArrowUpDown size={12} className="inline opacity-40" />
    : dir === -1 ? <ArrowDown size={12} className="inline" /> : <ArrowUp size={12} className="inline" />;

  return (
    <div>
      <PageHeader title="Cüzdan Sıralaması" icon={<Trophy size={22} />}
        subtitle="Takip ettiğimiz cüzdanların KENDİ al-sat performansı. Başlıklara tıklayıp sırala — kim ne kadar kazanıyor net gör."
        action={
          <button className="btn" onClick={rescan} disabled={scanning} title="Mevcut cüzdanları yeni kriterlerle yeniden puanlar (kredi harcamaz)">
            <RefreshCw size={15} className={scanning ? "animate-spin" : ""} />
            {scanning ? "Taranıyor…" : "Yeniden Tara"}
          </button>
        } />

      {/* Podyum — en çok kazandıran ilk 3 cüzdan */}
      {podium.length >= 3 && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          {[podium[1], podium[0], podium[2]].map((w, idx) => {
            const rank = idx === 1 ? 1 : idx === 0 ? 2 : 3; // ortadaki birinci
            const meta = {
              1: { cls: "podium-1", ico: Crown, col: "#fbbf24", lift: "md:-mt-3", h: "py-5" },
              2: { cls: "podium-2", ico: Medal, col: "#cbd5e1", lift: "md:mt-2", h: "py-4" },
              3: { cls: "podium-3", ico: Award, col: "#f59e0b", lift: "md:mt-3", h: "py-4" },
            }[rank]!;
            const Ico = meta.ico;
            return (
              <Link key={w.address} href={`/wallets/${w.address}`}
                className={`card podium ${meta.cls} ${meta.lift} ${meta.h} flex flex-col items-center text-center shine`}>
                <div className="podium-medal mb-2 h-10 w-10" style={{ background: `color-mix(in srgb, ${meta.col} 22%, transparent)`, color: meta.col }}>
                  <Ico size={20} />
                </div>
                <div className="font-mono text-xs font-semibold">{w.label || shortAddr(w.address)}</div>
                <div className="mt-1 text-lg font-black" style={{ color: w.realized_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                  <CountUp value={w.realized_pnl_sol ?? 0} decimals={3} signed suffix=" ◎" />
                </div>
                <div className="mt-0.5 text-[11px] muted">Puan {Math.round(w.score ?? 0)} · %{Math.round((w.win_rate || 0) * 100)} başarı</div>
              </Link>
            );
          })}
        </div>
      )}

      {backlog && (backlog.pending > 0 || isRunning || autoOn) && (
        <div className="card mb-4" style={{ borderColor: autoOn ? "var(--emerald)" : "var(--amber)", borderWidth: 1 }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold">🔍 Keşif Backlog'u: {backlog.pending.toLocaleString("tr-TR")} cüzdan analiz bekliyor</div>
              <p className="text-xs muted mt-1 max-w-xl">
                Bu cüzdanları yalnızca <b>adres</b> olarak biliyoruz; al-sat geçmişleri henüz zincirden çekilmedi.
                Analiz etmek <b>Helius kredisi harcar</b> (~10 kredi/cüzdan). <b>Otomatik analiz</b>'i açarsan
                arka planda sürekli (deploy'a dayanıklı) erir; kredi azalınca kapat.
              </p>
              <p className="text-xs mt-1" style={{ color: autoOn ? "var(--emerald)" : "var(--muted)" }}>
                {autoOn ? "🟢 Otomatik analiz AÇIK — arka planda sürekli işliyor. " : "⚪ Otomatik analiz kapalı. "}
                {drain?.ts && <>Son hareket {timeAgo(drain.ts)} · son turda +{drain.processed ?? 0} analiz, +{drain.tracked ?? 0} takibe{drain.remaining != null ? ` · ${Number(drain.remaining).toLocaleString("tr-TR")} kaldı` : ""}.</>}
                {!drain?.ts && "Henüz analiz turu çalışmadı."}
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              <button className={autoOn ? "btn-primary" : "btn"} onClick={() => toggleAuto(!autoOn)} disabled={autoBusy}>
                <RefreshCw size={14} className={autoOn ? "animate-spin" : ""} />
                {autoOn ? "Otomatik analizi durdur" : "Otomatik analizi başlat"}
              </button>
              <div className="flex flex-wrap justify-end gap-2">
                {[500, 2000].map((n) => (
                  <button key={n} className="btn-ghost text-xs" disabled={draining} onClick={() => drainBacklog(n)}
                    title="Tek seferlik sabit miktar (kredi kontrolü)">
                    +{n.toLocaleString("tr-TR")} (~{(n * 10 / 1000).toFixed(0)}k kredi)
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <Section title={`${rows.length} cüzdan · ${COLS.find((c) => c.key === sortKey)?.label}'a göre sıralı`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="py-2">#</th>
                <th>Cüzdan</th>
                <th>Durum</th>
                {COLS.map((c) => (
                  <th key={c.key} className={`sortable ${c.right ? "text-right" : ""}`} onClick={() => sortBy(c.key)}>
                    {c.label} <SortIco k={c.key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="stagger">
              {rows.map((r, i) => (
                <tr key={r.address} className="table-row border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="py-2">
                    <span className="grid h-5 w-5 place-items-center rounded-md text-[11px] font-bold"
                      style={{ background: i === 0 ? "var(--amber)" : i < 3 ? "color-mix(in srgb, var(--brand) 20%, transparent)" : "transparent",
                               color: i === 0 ? "#1b1300" : "var(--brand)" }}>{i + 1}</span>
                  </td>
                  <td>
                    <Link href={`/wallets/${r.address}`} className="clickable font-mono text-xs">
                      {r.label || shortAddr(r.address)}
                    </Link>
                  </td>
                  <td>
                    <span className="badge" style={{
                      background: r.status === "tracked" ? "color-mix(in srgb, var(--emerald) 16%, transparent)"
                        : r.status === "blocked" ? "color-mix(in srgb, var(--rose) 16%, transparent)" : "var(--bg2)",
                      color: r.status === "tracked" ? "var(--emerald)" : r.status === "blocked" ? "var(--rose)" : "var(--muted)" }}>
                      {r.status === "tracked" ? "Takipte" : r.status === "blocked" ? "Elendi" : r.status}
                    </span>
                  </td>
                  {COLS.map((c) => (
                    <td key={c.key} className={c.right ? "text-right" : ""}
                      style={c.key === "realized_pnl_sol" && r[c.key] != null ? { color: r[c.key] >= 0 ? "var(--emerald)" : "var(--rose)", fontWeight: 600 } : {}}>
                      {c.fmt ? c.fmt(r[c.key], r) : r[c.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { pumpfunToken, solscanToken } from "@/lib/links";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { StatCard } from "@/components/ui";
import { CountUp } from "@/components/CountUp";
import { EmptyState } from "@/components/EmptyState";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";
import { Wallet, TrendingUp, Flame, Snowflake, Coins, RefreshCw, AlertTriangle, ExternalLink, Info } from "lucide-react";

function pct(v?: number | null): string {
  if (v === null || v === undefined) return "—";
  const n = v * 100;
  return `${n >= 0 ? "+" : ""}${n.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}%`;
}

function solPrice(v?: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (Math.abs(v) < 0.00000001) return v.toExponential(3);
  return v.toLocaleString("tr-TR", { maximumFractionDigits: 10 });
}

function usd(v?: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toLocaleString("tr-TR", { maximumFractionDigits: 2 })}M`;
  if (v >= 1_000) return `$${(v / 1_000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}K`;
  return `$${v.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}`;
}

function timeAgo(ts?: string | null): string {
  if (!ts) return "—";
  const diff = Date.now() - new Date(ts).getTime();
  if (!Number.isFinite(diff)) return "—";
  const m = Math.max(0, Math.round(diff / 60000));
  if (m < 1) return "şimdi";
  if (m < 60) return `${m} dk önce`;
  const h = Math.round(m / 60);
  return `${h} sa önce`;
}

export default function Positions() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();
  const [connectedWallet, setConnectedWallet] = useState<string>("");
  const [portfolioTick, setPortfolioTick] = useState(0);
  const { data: positions, mutate } = useSWR<any[]>("/stats/positions", fetcher, { refreshInterval: 8000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 8000 });
  const portfolioPath = connectedWallet
    ? `/stats/wallet-portfolio?address=${encodeURIComponent(connectedWallet)}&fresh=true&history_fallback=false&das_balance=false&_=${portfolioTick}`
    : `/stats/wallet-portfolio?fresh=true&history_fallback=false&das_balance=false&_=${portfolioTick}`;
  const { data: portfolio, error: portfolioError, mutate: mutatePortfolio } = useSWR<any>(
    portfolioPath,
    fetcher,
    { refreshInterval: 3000, shouldRetryOnError: false, revalidateOnFocus: true }
  );
  const [busy, setBusy] = useState<string>("");

  const totalUnreal = (positions || []).reduce((a, p) => a + (p.unrealized_pnl_sol ?? 0), 0);
  const haveLive = (positions || []).some((p) => p.unrealized_pnl_sol != null);

  useEffect(() => {
    const saved = window.localStorage.getItem("connected_wallet_address");
    if (saved) setConnectedWallet(saved);
    const onAddress = (event: Event) => setConnectedWallet((event as CustomEvent<string>).detail || "");
    window.addEventListener("altay-wallet-address", onAddress);
    return () => window.removeEventListener("altay-wallet-address", onAddress);
  }, []);

  function publishWalletAddress(address: string) {
    window.dispatchEvent(new CustomEvent("altay-wallet-address", { detail: address }));
  }

  function walletProvider(): any {
    const w = window as any;
    return w.phantom?.solana || (w.solana?.isPhantom ? w.solana : null) || w.solflare || w.solana;
  }

  async function connectWallet() {
    const provider = walletProvider();
    if (!provider) {
      toast("error", "Phantom/Solflare bulunamadı. Tarayıcı cüzdan eklentisini aç.");
      return;
    }
    try {
      const res = await provider.connect();
      const address = res?.publicKey?.toString?.() || provider.publicKey?.toString?.();
      if (!address) throw new Error("Cüzdan adresi alınamadı");
      window.localStorage.setItem("connected_wallet_address", address);
      setConnectedWallet(address);
      publishWalletAddress(address);
      setPortfolioTick(Date.now());
      await mutatePortfolio();
      toast("success", `Cüzdan bağlandı: ${shortAddr(address)}`);
    } catch (e: any) {
      toast("error", e?.message || "Cüzdan bağlanamadı");
    }
  }

  async function disconnectWallet() {
    try {
      await walletProvider()?.disconnect?.();
    } catch {
      // Cüzdan disconnect desteklemese bile local seçimi temizlemek yeterli.
    }
    window.localStorage.removeItem("connected_wallet_address");
    setConnectedWallet("");
    publishWalletAddress("");
    setPortfolioTick(Date.now());
    await mutatePortfolio();
    toast("info", "Bağlı cüzdan kaldırıldı");
  }

  async function sell(p: any, fraction: number) {
    const pct = Math.round(fraction * 100);
    const isLive = p.mode === "live";
    const pnlNow = p.unrealized_pnl_sol != null
      ? ` Şu anki PnL: ${p.unrealized_pnl_sol >= 0 ? "+" : ""}${fmtNum(p.unrealized_pnl_sol, 4)} SOL (%${Math.round((p.unrealized_pnl_pct ?? 0) * 100)}).`
      : "";
    const ok = await confirm({
      title: `Pozisyonun %${pct}'ini sat`,
      body: `${shortAddr(p.token_mint)} pozisyonunun %${pct}'i ${isLive ? "GERÇEK CANLI emirle" : "paper simülasyonda"} satılacak.${pnlNow}`,
      confirmText: isLive ? `CANLI %${pct} sat` : `Evet, %${pct} sat`, danger: isLive || fraction === 1,
    });
    if (!ok) return;
    setBusy((p.position_id || p.token_mint) + fraction);
    try {
      const r: any = await apiSend(`/stats/positions/${p.token_mint}/sell?fraction=${fraction}`, "POST");
      await mutate();
      toast(r.realized_pnl_sol >= 0 ? "success" : "info",
        `${r.mode === "live" ? "CANLI" : "Paper"} %${pct} satıldı · PnL ${r.realized_pnl_sol >= 0 ? "+" : ""}${fmtNum(r.realized_pnl_sol, 4)} SOL`);
    } catch (e: any) { toast("error", e?.message || "Satılamadı"); }
    finally { setBusy(""); }
  }

  async function resetPaper() {
    const ok = await confirm({
      title: "Paper pozisyonları sıfırla?",
      body: "TÜM paper alım/satım kayıtları ve açık paper pozisyonları silinir. Canlı işlemler ve gerçek cüzdanın ETKİLENMEZ. Temiz bir test dönemi başlatmak için idealdir.",
      confirmText: "Paper'ı sıfırla", danger: true,
    });
    if (!ok) return;
    setBusy("reset");
    try {
      await apiSend("/trading/reset-paper", "POST");
      await Promise.all([mutate(), mutatePortfolio()]);
      toast("success", "Paper sıfırlandı — açık paper pozisyonları temizlendi");
    } catch (e: any) {
      toast("error", e?.message || "Sıfırlanamadı");
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      {dialog}
      <PageHeader title="Açık Pozisyonlar" icon={<Wallet size={22} />}
        subtitle="DB tahmini açık pozisyonlar + gerçek cüzdan snapshot'ı. Canlı PnL kesin fill değildir; gerçek cüzdan bakiyesi referanstır."
        action={
          <Link href="/history#reset" className="btn" title="Tüm sıfırlama işlemleri tek yerde">
            <RefreshCw size={14} /> Sıfırlama Merkezi
          </Link>
        } />
      <SectionTabs group="portfolio" />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Gerçekleşmemiş PnL" tone={totalUnreal >= 0 ? "var(--emerald)" : "var(--rose)"}
          accent={totalUnreal >= 0 ? "var(--emerald)" : "var(--rose)"}
          icon={totalUnreal >= 0 ? <Flame size={18} /> : <Snowflake size={18} />}
          value={haveLive ? <CountUp value={totalUnreal} decimals={4} signed suffix=" ◎" /> : "—"}
          hint={haveLive ? "açık pozisyonların canlı toplamı" : "canlı fiyat bekleniyor"} />
        <StatCard label="Açık Pozisyon" value={sum?.open_positions ?? positions?.length ?? "—"} tone="var(--sky)" icon={<Coins size={18} />} />
        <StatCard label="Açık Risk (maliyet)" value={`${sum?.open_exposure_sol ?? "—"} SOL`} tone="var(--amber)" />
        <StatCard label="Bugünkü Paper PnL" value={`${sum?.today_realized_pnl_sol ?? "—"} SOL`} tone="var(--violet)" icon={<TrendingUp size={18} />}
          accent={(sum?.today_realized_pnl_sol ?? 0) >= 0 ? "var(--emerald)" : "var(--rose)"} />
      </div>

      <div className="card mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Gerçek Cüzdan Portföyü</div>
            <p className="text-xs muted">
              Bu bölüm DB tahmini değil; doğrudan Solana RPC üzerinden gerçek cüzdan bakiyesidir.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {connectedWallet ? (
              <>
                <span className="badge" style={{ background: "color-mix(in srgb, var(--emerald) 16%, transparent)", color: "var(--emerald)" }}>
                  Wallet bağlı: {shortAddr(connectedWallet)}
                </span>
                <button className="btn-ghost" onClick={disconnectWallet}>Bağlantıyı kes</button>
              </>
            ) : (
              <button className="btn-primary" onClick={connectWallet}>
                <Wallet size={14} /> Connect Wallet
              </button>
            )}
            <button className="btn" onClick={() => { setPortfolioTick(Date.now()); mutatePortfolio(); }}>
              <RefreshCw size={14} /> Yenile
            </button>
          </div>
        </div>
        {portfolioError ? (
          <div className="flex items-center gap-2 text-sm" style={{ color: "var(--amber)" }}>
            <AlertTriangle size={16} />
            Portföy adresi okunamadı. Connect Wallet yap veya .env içine TRADING_WALLET_ADDRESS=public_adres ekle.
          </div>
        ) : portfolio ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard label="On-chain SOL" value={`${fmtNum(portfolio.sol_balance, 4)} SOL`} tone="var(--brand)" />
              <StatCard label="On-chain Toplam" value={`${fmtNum(portfolio.total_value_sol, 4)} SOL`} tone="var(--emerald)" />
              <StatCard label="Token Sayısı" value={portfolio.token_count ?? 0} tone="var(--violet)" />
              <StatCard label="Adres" value={shortAddr(portfolio.address)} tone="var(--sky)" />
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
              {portfolio.tokens?.length > 0 ? portfolio.tokens.slice(0, 24).map((t: any) => (
                <div key={t.account || t.mint} className="rounded-lg border p-3" style={{ borderColor: "var(--border)", background: "linear-gradient(180deg, color-mix(in srgb, var(--card) 92%, var(--brand) 8%), var(--card))" }}>
                  <div className="flex items-start gap-3">
                    <div className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>
                      {t.image ? <img src={t.image} alt="" className="h-full w-full object-cover" /> : <Coins size={20} className="muted" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold">{t.symbol || t.name || shortAddr(t.mint)}</div>
                      <div className="font-mono text-[11px] muted">{shortAddr(t.mint)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-bold" style={{ color: t.value_sol != null ? "var(--emerald)" : "var(--muted)" }}>
                        {t.value_sol == null ? "—" : `${fmtNum(t.value_sol, 4)} SOL`}
                      </div>
                      <div className="text-[11px] muted">{fmtNum(t.amount, 4)} adet</div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-md p-2" style={{ background: "var(--bg2)" }}>
                      <div className="muted">Fiyat</div>
                      <div className="font-semibold">{t.price_sol == null ? "—" : `${fmtNum(t.price_sol, 10)} SOL`}</div>
                    </div>
                    <div className="rounded-md p-2" style={{ background: "var(--bg2)" }}>
                      <div className="muted">Likidite</div>
                      <div className="font-semibold">{t.liquidity_sol == null ? "—" : `${fmtNum(t.liquidity_sol, 2)} SOL`}</div>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <a href={pumpfunToken(t.mint)} target="_blank" rel="noreferrer" className="btn text-xs">Pump.fun</a>
                    <a href={solscanToken(t.mint)} target="_blank" rel="noreferrer" className="btn-ghost text-xs">Solscan</a>
                  </div>
                </div>
              )) : (
                <div className="rounded-lg border p-4 text-sm muted lg:col-span-2 xl:col-span-4" style={{ borderColor: "var(--border)" }}>
                  <div>Token bakiyesi bulunamadı. Yenile'ye bas; hâlâ 0 görünüyorsa bağlı cüzdan adresi Phantom'daki portföy adresiyle aynı mı kontrol et.</div>
                  {portfolio.debug && (
                    <div className="mt-2 font-mono text-[11px]">
                      token_accounts={portfolio.debug.token_account_rows ?? 0} · das_assets={portfolio.debug.das_assets ?? 0} · enhanced_tx={portfolio.debug.enhanced_transactions ?? 0} · enhanced_mints={portfolio.debug.enhanced_positive_mints ?? 0}
                    </div>
                  )}
                </div>
              )}
            </div>
            <p className="mt-3 text-xs muted">
              Son zincir okuması: {portfolio.as_of ? new Date(portfolio.as_of).toLocaleTimeString("tr-TR") : "—"}
              {" · "}Kaynak: {portfolio.source} / {portfolio.commitment}
              {portfolio.history_fallback_used ? " · geçmiş fallback açık" : ""}
              {portfolio.das_balance_used ? " · DAS bakiye açık" : ""}
            </p>
          </>
        ) : (
          <div className="text-sm muted">Gerçek cüzdan portföyü yükleniyor…</div>
        )}
      </div>

      <div className="card mt-4 overflow-x-auto">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Açık Pozisyon Detayları</div>
            <p className="text-xs muted">
              Giriş fiyatı, efektif maliyet, anlık fiyat ve PnL ayrılır. Böylece token %10 düşerken PnL neden %19 olabilir net görünür.
            </p>
          </div>
          <button className="btn" onClick={() => mutate()}><RefreshCw size={14} /> Fiyatları yenile</button>
        </div>
        {positions && positions.length > 0 ? (
          <table className="w-full min-w-[1180px] text-sm">
            <thead><tr className="border-b text-left muted" style={{ borderColor: "var(--border)" }}>
              <th className="p-3">Token</th>
              <th className="p-3">Giriş / Maliyet</th>
              <th className="p-3">Anlık Piyasa</th>
              <th className="p-3">Hareket Analizi</th>
              <th className="p-3 text-right">Gerçekleşmemiş PnL</th>
              <th className="p-3 text-center">Sat</th>
            </tr></thead>
            <tbody>
              {positions.map((p) => {
                const up = (p.unrealized_pnl_sol ?? 0) >= 0;
                const col = p.unrealized_pnl_sol == null ? "var(--muted)" : up ? "var(--emerald)" : "var(--rose)";
                const title = p.token_symbol || p.token_name || shortAddr(p.token_mint);
                const modeColor = p.mode === "live" ? "var(--rose)" : "var(--sky)";
                const marketMove = p.market_move_pct;
                const feeDrag = p.fee_drag_pct;
                return (
                  <tr key={p.position_id || p.token_mint} className="table-row border-b last:border-0 align-top" style={{ borderColor: "var(--border)" }}>
                    <td className="p-3">
                      <div className="flex min-w-[250px] items-start gap-3">
                        <div className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-2xl border" style={{ borderColor: "var(--border)", background: "var(--bg2)" }}>
                          {p.token_image ? <img src={p.token_image} alt="" className="h-full w-full object-cover" /> : <Coins size={20} className="muted" />}
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Link href={`/tokens/${p.token_mint}`} className="clickable truncate text-base font-extrabold">{title}</Link>
                            <span className="badge" style={{ background: `color-mix(in srgb, ${modeColor} 18%, transparent)`, color: modeColor }}>{p.mode === "live" ? "LIVE" : "PAPER"}</span>
                            {p.estimated && <span className="badge" title={p.estimation_note || "Canlı PnL tahminidir"}
                              style={{ background: "color-mix(in srgb, var(--amber) 18%, transparent)", color: "var(--amber)" }}>tahmini</span>}
                            {p.suspicious && <span className="badge" title={p.suspicious_reason === "unrealistic_unrealized_pnl" ? "Giriş fiyatı/canlı fiyat oranı imkansız görünüyor; açık PnL gerçek kâr gibi gösterilmedi." : "Değer havuz likiditesini aştığı için sınırlandı."}
                              style={{ background: "color-mix(in srgb, var(--amber) 18%, transparent)", color: "var(--amber)" }}>veri kontrol</span>}
                          </div>
                          <div className="mt-1 font-mono text-[11px] muted">{shortAddr(p.token_mint)} · {fmtNum(p.qty_raw ?? p.qty, 4)} adet</div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <a href={pumpfunToken(p.token_mint)} target="_blank" rel="noreferrer" className="btn-ghost text-xs">Pump.fun <ExternalLink size={11} /></a>
                            <a href={p.pair_url || solscanToken(p.token_mint)} target="_blank" rel="noreferrer" className="btn-ghost text-xs">Piyasa <ExternalLink size={11} /></a>
                          </div>
                          <div className="mt-2 text-[11px] muted">Lider/Kaynak: <span className="font-mono">{p.wallet_address === "AI_TRADE" ? "AI_TRADE" : shortAddr(p.wallet_address)}</span></div>
                        </div>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="grid min-w-[230px] gap-2 text-xs">
                        <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                          <div className="muted">Alım maliyeti</div>
                          <div className="text-base font-extrabold">{fmtNum(p.cost_sol, 4)} SOL</div>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                            <div className="muted">Giriş fiyatı</div>
                            <div className="font-semibold">{solPrice(p.avg_entry_price_sol)} SOL</div>
                          </div>
                          <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }} title="Fee dahil efektif maliyet fiyatı. PnL yüzdesi buna göre hesaplanır.">
                            <div className="muted">Efektif giriş</div>
                            <div className="font-semibold">{solPrice(p.effective_entry_price_sol)} SOL</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 text-[11px] muted" title="Paper PnL, token fiyat hareketine ek olarak priority fee ve slippage maliyetini de içerir.">
                          <Info size={12} /> Fee/slippage etkisi: {pct(feeDrag)} · fee {fmtNum(p.fee_sol_open, 5)} SOL
                        </div>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="grid min-w-[210px] gap-2 text-xs">
                        <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                          <div className="muted">Şu anki değer</div>
                          <div className="text-base font-extrabold">{p.current_value_sol == null ? "—" : `${fmtNum(p.current_value_sol, 4)} SOL`}</div>
                        </div>
                        <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                          <div className="muted">Anlık fiyat</div>
                          <div className="font-semibold">{solPrice(p.current_price_sol)} SOL</div>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                            <div className="muted">MCap</div>
                            <div className="font-semibold">{usd(p.market_cap_usd || p.fdv_usd)}</div>
                          </div>
                          <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                            <div className="muted">Likidite</div>
                            <div className="font-semibold">{p.liquidity_sol == null ? "—" : `${fmtNum(p.liquidity_sol, 2)} SOL`}</div>
                          </div>
                        </div>
                        <div className="text-[11px] muted">Kaynak: {p.price_source || "—"} · {p.price_as_of ? timeAgo(p.price_as_of) : "—"}</div>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="grid min-w-[220px] gap-2 text-xs">
                        <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                          <div className="muted">Token hareketi</div>
                          <div className="text-base font-extrabold" style={{ color: (marketMove ?? 0) >= 0 ? "var(--emerald)" : "var(--rose)" }}>{pct(marketMove)}</div>
                          <div className="text-[11px] muted">giriş fiyatı → anlık fiyat</div>
                        </div>
                        <div className="rounded-lg p-2" style={{ background: "var(--bg2)" }}>
                          <div className="muted">PnL farkı neden olur?</div>
                          <div className="text-[11px] leading-relaxed muted">{p.pnl_explainer}</div>
                        </div>
                        <div className="text-[11px] muted">Açılış: {p.opened_at ? new Date(p.opened_at).toLocaleTimeString("tr-TR") : "—"} · yaş {p.age_minutes ?? "—"} dk</div>
                      </div>
                    </td>
                    <td className="p-3 text-right font-bold" style={{ color: col }}>
                      {p.unrealized_pnl_sol == null ? "—" : (
                        <span className="inline-flex min-w-[120px] flex-col items-end leading-tight">
                          <span className="text-lg">{up ? "+" : ""}{fmtNum(p.unrealized_pnl_sol, 4)} ◎</span>
                          <span className="text-xs font-semibold">{up ? "▲" : "▼"} %{Math.abs(Math.round((p.unrealized_pnl_pct ?? 0) * 100))}</span>
                        </span>
                      )}
                    </td>
                    <td className="p-3">
                      <div className="flex items-center justify-center gap-2">
                        <button className="btn" disabled={!!busy} onClick={() => sell(p, 0.5)}>%50</button>
                        <button className="btn-danger" disabled={!!busy} onClick={() => sell(p, 1)}>%100</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <EmptyState icon={Wallet} title="Açık pozisyon yok" hint="AI veya Copy motoru alım yaptıkça pozisyonlar burada detaylı fiyat karşılaştırmasıyla görünür." />}
      </div>

      <p className="mt-3 text-xs muted">
        Gerçekleşmemiş PnL anlık piyasa fiyatıyla hesaplanır; fiyat/fill doğrulanamayan canlı kayıtlar tahmini gösterilir.
        PAPER satışı simülasyondur; LIVE satışı PumpPortal üzerinden gerçek emir gönderir. Yatırım tavsiyesi değildir.
      </p>
    </div>
  );
}

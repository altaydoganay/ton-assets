"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ChevronDown, RefreshCw, Wallet } from "lucide-react";
import { fetcher, fmtNum, shortAddr } from "@/lib/api";
import { useToast } from "./Toast";

function provider(kind?: "phantom" | "solflare"): any {
  const w = window as any;
  if (kind === "phantom") {
    if (w.phantom?.solana) return w.phantom.solana;
    if (w.solana?.isPhantom) return w.solana;
    return null;
  }
  if (kind === "solflare") {
    if (w.solflare) return w.solflare;
    if (w.solana?.isSolflare) return w.solana;
    return null;
  }
  return w.phantom?.solana || (w.solana?.isPhantom ? w.solana : null) || w.solflare || w.solana;
}

function publish(address: string) {
  window.localStorage.setItem("connected_wallet_address", address);
  window.dispatchEvent(new CustomEvent("altay-wallet-address", { detail: address }));
}

function clear() {
  window.localStorage.removeItem("connected_wallet_address");
  window.dispatchEvent(new CustomEvent("altay-wallet-address", { detail: "" }));
}

export function WalletConnect() {
  const [address, setAddress] = useState("");
  const [open, setOpen] = useState(false);
  const [portfolioOpen, setPortfolioOpen] = useState(false);
  const [lastKind, setLastKind] = useState<"phantom" | "solflare" | undefined>();
  const [portfolioTick, setPortfolioTick] = useState(0);
  const toast = useToast();
  const portfolioPath = address
    ? `/stats/wallet-portfolio?address=${encodeURIComponent(address)}&fresh=true&history_fallback=false&das_balance=false&_=${portfolioTick}`
    : null;
  const { data: portfolio, error: portfolioError, mutate } = useSWR<any>(
    portfolioPath,
    portfolioPath ? fetcher : null,
    { refreshInterval: 3000, shouldRetryOnError: false, revalidateOnFocus: true }
  );

  useEffect(() => {
    setAddress(window.localStorage.getItem("connected_wallet_address") || "");
    const onAddress = (event: Event) => setAddress((event as CustomEvent<string>).detail || "");
    window.addEventListener("altay-wallet-address", onAddress);
    return () => window.removeEventListener("altay-wallet-address", onAddress);
  }, []);

  async function connect(kind?: "phantom" | "solflare") {
    setOpen(false);
    const p = provider(kind);
    if (!p) {
      toast("error", kind === "phantom" ? "Phantom bulunamadı" : kind === "solflare" ? "Solflare bulunamadı" : "Cüzdan bulunamadı");
      return;
    }
    try {
      const res = await p.connect();
      const next = res?.publicKey?.toString?.() || p.publicKey?.toString?.();
      if (!next) throw new Error("Cüzdan adresi alınamadı");
      setLastKind(kind);
      publish(next);
      setPortfolioTick(Date.now());
      setPortfolioOpen(true);
      toast("success", `Cüzdan bağlandı: ${shortAddr(next)}`);
    } catch (e: any) {
      toast("error", e?.message || "Cüzdan bağlanamadı");
    }
  }

  async function disconnect() {
    try {
      await provider(lastKind)?.disconnect?.();
    } catch {
      // Cüzdan eklentisi disconnect desteklemese bile panel seçimini temizleriz.
    }
    clear();
    setPortfolioOpen(false);
    toast("info", "Cüzdan bağlantısı kaldırıldı");
  }

  if (address) {
    return (
      <div className="relative">
        <button className="btn" onClick={() => setPortfolioOpen((v) => !v)} title="Bağlı cüzdan portföyü">
          <Wallet size={15} /> {shortAddr(address)} <ChevronDown size={14} />
        </button>
        {portfolioOpen && (
          <div className="absolute right-0 top-[calc(100%+6px)] z-50 w-[360px] max-w-[calc(100vw-24px)] overflow-hidden rounded-lg border shadow-xl"
            style={{ background: "var(--card)", borderColor: "var(--border)" }}>
            <div className="border-b p-3" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-xs muted">Bağlı cüzdan</div>
                  <div className="font-mono text-sm font-semibold">{shortAddr(address)}</div>
                </div>
                <button className="btn-ghost" onClick={() => { setPortfolioTick(Date.now()); mutate(); }} title="Portföyü yenile">
                  <RefreshCw size={14} />
                </button>
              </div>
            </div>
            {portfolioError ? (
              <div className="p-3 text-sm" style={{ color: "var(--amber)" }}>
                Portföy okunamadı. RPC/Helius bağlantısını veya API anahtarını kontrol et.
              </div>
            ) : !portfolio ? (
              <div className="p-3 text-sm muted">Portföy yükleniyor…</div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2 p-3">
                  <div className="rounded-md border p-2" style={{ borderColor: "var(--border)" }}>
                    <div className="text-[11px] muted">SOL bakiye</div>
                    <div className="font-bold">{fmtNum(portfolio.sol_balance, 4)} SOL</div>
                  </div>
                  <div className="rounded-md border p-2" style={{ borderColor: "var(--border)" }}>
                    <div className="text-[11px] muted">Toplam değer</div>
                    <div className="font-bold">{fmtNum(portfolio.total_value_sol, 4)} SOL</div>
                  </div>
                  <div className="rounded-md border p-2" style={{ borderColor: "var(--border)" }}>
                    <div className="text-[11px] muted">Token</div>
                    <div className="font-bold">{portfolio.token_count ?? 0}</div>
                  </div>
                  <div className="rounded-md border p-2" style={{ borderColor: "var(--border)" }}>
                    <div className="text-[11px] muted">Fiyatlanan</div>
                    <div className="font-bold">{portfolio.priced_token_count ?? 0}</div>
                  </div>
                </div>
                <div className="max-h-72 overflow-y-auto border-t" style={{ borderColor: "var(--border)" }}>
                  {portfolio.tokens?.length ? (
                    portfolio.tokens.slice(0, 8).map((t: any) => (
                      <div key={t.account || t.mint} className="flex items-center justify-between gap-3 border-b px-3 py-2 last:border-0" style={{ borderColor: "var(--border)" }}>
                        <div>
                          <Link href={`/tokens/${t.mint}`} className="clickable font-mono text-xs">{shortAddr(t.mint)}</Link>
                          <div className="text-[11px] muted">{fmtNum(t.amount, 4)} adet</div>
                        </div>
                        <div className="text-right text-sm font-semibold">
                          {t.value_sol == null ? "—" : `${fmtNum(t.value_sol, 4)} SOL`}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="px-3 py-3 text-sm muted">
                  <div>Token bakiyesi yok.</div>
                      {portfolio.debug && (
                        <div className="mt-1 font-mono text-[11px]">
                          token_accounts={portfolio.debug.token_account_rows ?? 0} · das={portfolio.debug.das_assets ?? 0} · tx={portfolio.debug.enhanced_transactions ?? 0} · mints={portfolio.debug.enhanced_positive_mints ?? 0}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div className="border-t px-3 py-2 text-[11px] muted" style={{ borderColor: "var(--border)" }}>
                  Son okuma: {portfolio.as_of ? new Date(portfolio.as_of).toLocaleTimeString("tr-TR") : "—"}
                  {" · "}{portfolio.source} / {portfolio.commitment}
                </div>
              </>
            )}
            <div className="flex items-center justify-between gap-2 border-t p-3" style={{ borderColor: "var(--border)" }}>
              <Link href="/positions" className="btn text-xs" onClick={() => setPortfolioOpen(false)}>Detaylı Portföy</Link>
              <button className="btn-ghost text-xs" onClick={disconnect}>Bağlantıyı kes</button>
            </div>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="relative">
      <button className="btn-primary" onClick={() => setOpen((v) => !v)} title="Portföy görüntülemek için cüzdan bağla">
        <Wallet size={15} /> Connect Wallet <ChevronDown size={14} />
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-50 min-w-44 overflow-hidden rounded-lg border shadow-xl"
          style={{ background: "var(--card)", borderColor: "var(--border)" }}>
          <button className="block w-full px-3 py-2 text-left text-sm hover:bg-white/5" onClick={() => connect("phantom")}>
            Phantom
          </button>
          <button className="block w-full px-3 py-2 text-left text-sm hover:bg-white/5" onClick={() => connect("solflare")}>
            Solflare
          </button>
        </div>
      )}
    </div>
  );
}

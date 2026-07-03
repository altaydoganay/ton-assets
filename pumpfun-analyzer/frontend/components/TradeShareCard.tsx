"use client";
import { useEffect, useRef } from "react";

/**
 * Kâr/Zarar paylaşım kartı (banner).
 *
 * Kullanıcının verdiği maskot arka planları (frontend/public/mascots/*.jpg)
 * üzerine işlem bilgileri canvas ile yazılır. Maskot, pozisyonun sonucuna göre
 * OTOMATİK seçilir: artıda sevinen maskotlardan, ekside üzülen/sinirlenen
 * maskotlardan rastgele (ama aynı işlem için sabit) biri gelir.
 */

export type TradeCardData = {
  symbol: string;
  pnlPct: number;
  initialSol: number;
  worthSol: number;
  mode?: "ai" | "copy";
  kind?: "paper" | "live";
  when?: string;
  mascot?: string;          // elle seçim (opsiyonel)
};

// Sevinen / güvenli maskotlar → ARTI pozisyon
export const MASCOTS_POSITIVE = [
  "01_win_frog_happy",
  "07_confidence_lion_proud",
  "10_fast_entry_rabbit_excited",
  "11_whale_wallet_confident",
];
// Üzülen / sinirlenen / panikleyen maskotlar → EKSİ pozisyon
export const MASCOTS_NEGATIVE = [
  "02_loss_turtle_sad",
  "03_bad_trade_bull_angry",
  "05_volatility_hamster_panic",
  "06_rug_risk_fox_suspicious",
  "09_loss_penguin_crying",
];

export function mascotSrc(name: string): string {
  return `/mascots/${name}.jpg`;
}

/** Pozisyona göre maskot seç — aynı işlem hep aynı maskotu gösterir. */
export function pickMascot(d: TradeCardData): string {
  if (d.mascot) return d.mascot;
  const pool = d.pnlPct >= 0 ? MASCOTS_POSITIVE : MASCOTS_NEGATIVE;
  const key = `${d.symbol}|${d.when || ""}|${Math.round(d.pnlPct * 100)}`;
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 16777619); }
  return pool[(h >>> 0) % pool.length];
}

type Tone = { label: string; accent: string; soft: string };
function toneFor(pct: number): Tone {
  if (pct >= 100) return { label: "AYA GİDİYORUZ 🚀", accent: "#22d3ee", soft: "#a5f3fc" };
  if (pct >= 30)  return { label: "COŞTU 🔥",         accent: "#34d399", soft: "#a7f3d0" };
  if (pct >= 5)   return { label: "CEBE KOYDUK 😎",   accent: "#4ade80", soft: "#bbf7d0" };
  if (pct >= 0)   return { label: "UFAK AMA ARTI 🙂", accent: "#86efac", soft: "#dcfce7" };
  if (pct >= -15) return { label: "UFAK TIRPAN 😐",   accent: "#fbbf24", soft: "#fde68a" };
  if (pct >= -40) return { label: "CANIMIZ YANDI 😵", accent: "#fb7185", soft: "#fecdd3" };
  return { label: "REKT OLDUK 💀", accent: "#ef4444", soft: "#fecaca" };
}

const W = 1280, H = 720;
const imgCache = new Map<string, HTMLImageElement>();

function loadImg(src: string): Promise<HTMLImageElement> {
  const cached = imgCache.get(src);
  if (cached && cached.complete && cached.naturalWidth) return Promise.resolve(cached);
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => { imgCache.set(src, img); res(img); };
    img.onerror = () => rej(new Error("maskot yüklenemedi"));
    img.src = src;
  });
}

function sol(n: number): string {
  return `${n.toLocaleString("en-US", { maximumFractionDigits: 3, minimumFractionDigits: 3 })} SOL`;
}
function pctStr(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Kartı verilen canvas'a çizer (arka plan + metin). */
export async function renderTradeCard(canvas: HTMLCanvasElement, d: TradeCardData, scale = 1) {
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  const t = toneFor(d.pnlPct);
  const win = d.pnlPct >= 0;

  // Arka plan (maskot) — yüklenemezse düz koyu zemin
  try {
    const img = await loadImg(mascotSrc(pickMascot(d)));
    ctx.drawImage(img, 0, 0, W, H);
  } catch {
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, W, H);
  }

  // Sol karartma (metin okunaklılığı) — soldan sağa doğru şeffaflaşır
  const gx = ctx.createLinearGradient(0, 0, W * 0.72, 0);
  gx.addColorStop(0, "rgba(5,8,14,0.90)");
  gx.addColorStop(0.55, "rgba(5,8,14,0.42)");
  gx.addColorStop(1, "rgba(5,8,14,0)");
  ctx.fillStyle = gx;
  ctx.fillRect(0, 0, W, H);
  // Alt karartma (marka barı)
  const gy = ctx.createLinearGradient(0, H - 110, 0, H);
  gy.addColorStop(0, "rgba(5,8,14,0)");
  gy.addColorStop(1, "rgba(5,8,14,0.82)");
  ctx.fillStyle = gy;
  ctx.fillRect(0, H - 110, W, 110);

  const F = "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif";
  const X = 72;
  ctx.textBaseline = "alphabetic";

  // Mod rozeti
  const modeTag = d.mode === "ai" ? "AI TRADE" : d.mode === "copy" ? "COPY TRADE" : "SNIPER";
  const kind = d.kind === "live" ? "CANLI" : "PAPER";
  const badge = `${modeTag} · ${kind}`;
  ctx.font = `800 20px ${F}`;
  const bw = ctx.measureText(badge).width + 52;
  ctx.fillStyle = `${t.accent}26`;
  roundRect(ctx, X, 60, bw, 42, 21); ctx.fill();
  ctx.fillStyle = t.accent;
  ctx.beginPath(); ctx.arc(X + 24, 81, 6, 0, Math.PI * 2); ctx.fill();
  ctx.fillText(badge, X + 40, 88);

  // Sembol
  ctx.font = `900 64px ${F}`;
  ctx.fillStyle = "#ffffff";
  ctx.fillText(d.symbol, X, 176);
  const sw = ctx.measureText(d.symbol).width;
  ctx.font = `700 34px ${F}`;
  ctx.fillStyle = "#7c8aa5";
  ctx.fillText("/SOL", X + sw + 14, 176);

  // Büyük yüzde
  ctx.font = `900 132px ${F}`;
  ctx.fillStyle = t.accent;
  ctx.shadowColor = `${t.accent}66`;
  ctx.shadowBlur = 40;
  ctx.fillText(pctStr(d.pnlPct), X - 2, 320);
  ctx.shadowBlur = 0;

  // Başlangıç / Güncel
  ctx.font = `600 24px ${F}`;
  ctx.fillStyle = "#93a2bd";
  ctx.fillText("Başlangıç", X, 382);
  ctx.fillText("Güncel", X, 424);
  ctx.font = `800 26px ${F}`;
  ctx.fillStyle = "#e2e8f0";
  ctx.fillText(sol(d.initialSol), X + 168, 382);
  ctx.fillStyle = t.accent;
  ctx.fillText(sol(d.worthSol), X + 168, 424);

  // Sonuç etiketi
  ctx.font = `900 30px ${F}`;
  const lw = ctx.measureText(t.label).width + 44;
  ctx.fillStyle = `${t.accent}26`;
  roundRect(ctx, X, 452, lw, 54, 14); ctx.fill();
  ctx.fillStyle = t.soft;
  ctx.fillText(t.label, X + 22, 489);

  // Marka + tarih
  ctx.font = `900 26px ${F}`;
  ctx.fillStyle = "#e6edf7";
  ctx.fillText("ALTAY · AI Trade Panel", X, H - 32);
  if (d.when) {
    ctx.font = `600 20px ${F}`;
    ctx.fillStyle = "#8592ab";
    ctx.textAlign = "right";
    ctx.fillText(new Date(d.when).toLocaleString("tr-TR"), W - 64, H - 32);
    ctx.textAlign = "left";
  }
  void win;
}

/** Kartı PNG olarak indirir (2x). */
export async function downloadTradeCardPng(d: TradeCardData, filename = "islem-karti.png") {
  const canvas = document.createElement("canvas");
  await renderTradeCard(canvas, d, 2);
  await new Promise<void>((res) => canvas.toBlob((b) => {
    if (b) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    }
    res();
  }, "image/png"));
}

/** Ekranda kartı gösteren React sarmalayıcı (canvas). */
export function TradeShareCard({ data, className }: { data: TradeCardData; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (c) { renderTradeCard(c, data, 1).catch(() => {}); }
  }, [data]);
  return (
    <canvas
      ref={ref}
      className={className}
      style={{ width: "100%", height: "auto", display: "block", borderRadius: 16, aspectRatio: `${W} / ${H}` }}
    />
  );
}

/** Kapanmış bir satış (sell) satırından kart verisi türetir. */
export function cardFromSellRow(r: any, opts?: { symbol?: string; mode?: "ai" | "copy"; kind?: "paper" | "live" }): TradeCardData | null {
  if (!r || r.side !== "sell" || r.realized_pnl_sol == null) return null;
  const worth = Number(r.sol_amount || 0);
  const pnl = Number(r.realized_pnl_sol || 0);
  const initial = worth - pnl;
  const pct = initial > 1e-9 ? (pnl / initial) * 100 : 0;
  const short = String(r.token_mint || "").slice(0, 4).toUpperCase();
  return {
    symbol: opts?.symbol || short || "TOKEN",
    pnlPct: pct,
    initialSol: initial,
    worthSol: worth,
    mode: opts?.mode,
    kind: opts?.kind || (r.status ? "live" : "paper"),
    when: r.created_at,
  };
}

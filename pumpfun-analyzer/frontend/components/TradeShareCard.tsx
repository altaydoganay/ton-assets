"use client";
import { useMemo, useRef } from "react";

/**
 * Kâr/Zarar paylaşım kartı (banner).
 *
 * Bağımlılıksız, tek parça SVG üretir; PNG olarak indirilebilir. İllüstrasyonlar
 * TELİFSİZDİR: SpongeBob/Pepe/He-Man gibi karakterler DEĞİL, kendi emoji tabanlı
 * "mizah kademelerimiz" kullanılır (kâr yüzdesine göre otomatik seçilir).
 */

export type TradeCardData = {
  symbol: string;          // token sembolü ya da kısa mint
  pnlPct: number;          // yüzde (ör. +54.15)
  initialSol: number;      // giriş maliyeti (SOL)
  worthSol: number;        // güncel/çıkış değeri (SOL)
  mode?: "ai" | "copy";    // rozet
  kind?: "paper" | "live"; // alt bilgi
  when?: string;           // ISO tarih (opsiyonel)
};

type Tier = {
  key: string;
  emoji: string;
  label: string;    // Türkçe mizah başlığı
  accent: string;   // ana vurgu rengi
  glow: string;     // arka ışıma
};

/** Kâr yüzdesine göre kademe (mizah + renk). */
export function tierFor(pct: number): Tier {
  if (pct >= 100) return { key: "moon", emoji: "🚀", label: "AYA GİDİYORUZ", accent: "#22d3ee", glow: "#0e7490" };
  if (pct >= 30)  return { key: "fire", emoji: "🔥", label: "COŞTU", accent: "#34d399", glow: "#065f46" };
  if (pct >= 5)   return { key: "win",  emoji: "😎", label: "CEBE KOYDUK", accent: "#4ade80", glow: "#166534" };
  if (pct >= 0)   return { key: "flat_up", emoji: "🙂", label: "UFAK AMA ARTI", accent: "#86efac", glow: "#14532d" };
  if (pct >= -15) return { key: "dip",  emoji: "😐", label: "UFAK TIRPAN", accent: "#fbbf24", glow: "#92400e" };
  if (pct >= -40) return { key: "loss", emoji: "😵", label: "CANIMIZ YANDI", accent: "#fb7185", glow: "#9f1239" };
  return { key: "rekt", emoji: "💀", label: "REKT OLDUK", accent: "#ef4444", glow: "#7f1d1d" };
}

const W = 1200, H = 675;

function esc(s: string): string {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function sol(n: number): string {
  return `${n.toLocaleString("en-US", { maximumFractionDigits: 3, minimumFractionDigits: 3 })} SOL`;
}
function pctStr(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

/** Tek parça SVG dizesi. Hem ekranda gösterim hem PNG export bunu kullanır. */
export function buildTradeCardSVG(d: TradeCardData): string {
  const t = tierFor(d.pnlPct);
  const win = d.pnlPct >= 0;
  const modeTag = d.mode === "ai" ? "AI TRADE" : d.mode === "copy" ? "COPY TRADE" : "SNIPER";
  const kind = d.kind === "live" ? "CANLI" : "PAPER";
  const dateStr = d.when ? new Date(d.when).toLocaleString("tr-TR") : "";

  // Arka plan mum çubukları (dekoratif, rastgele değil — sabit desen)
  const bars = [80, 170, 260, 350, 440, 530, 620].map((x, i) => {
    const h = [120, 70, 150, 90, 180, 60, 140][i];
    const y = H - 130 - h;
    const c = i % 3 === 0 ? "#1f8a5a" : i % 3 === 1 ? "#7f1d3a" : "#334155";
    return `<rect x="${x}" y="${y}" width="34" height="${h}" rx="6" fill="${c}" opacity="0.16"/>
            <rect x="${x + 15}" y="${y - 20}" width="4" height="${h + 40}" fill="${c}" opacity="0.16"/>`;
  }).join("");

  // Kazanç/kayıp oku (mascot arkası)
  const arrow = win
    ? `<path d="M980 470 L1080 300 L1180 470 L1130 470 L1130 560 L1030 560 L1030 470 Z" fill="${t.accent}" opacity="0.14"/>`
    : `<path d="M980 300 L1080 470 L1180 300 L1130 300 L1130 210 L1030 210 L1030 300 Z" fill="${t.accent}" opacity="0.14"/>`;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Inter, ui-sans-serif, system-ui, sans-serif">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0a0f1a"/>
      <stop offset="1" stop-color="#0f1626"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="45%" r="60%">
      <stop offset="0" stop-color="${t.glow}" stop-opacity="0.9"/>
      <stop offset="1" stop-color="${t.glow}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="pct" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="${t.accent}"/>
      <stop offset="1" stop-color="${win ? "#a7f3d0" : "#fecaca"}"/>
    </linearGradient>
  </defs>

  <rect width="${W}" height="${H}" fill="url(#bg)"/>
  <g>${bars}</g>
  <rect width="${W}" height="${H}" fill="none"/>
  <circle cx="960" cy="300" r="300" fill="url(#glow)"/>
  ${arrow}

  <!-- Sol sütun -->
  <g transform="translate(64,74)">
    <rect x="0" y="0" width="${modeTag.length * 15 + 118}" height="40" rx="20" fill="${t.accent}" opacity="0.14"/>
    <circle cx="24" cy="20" r="7" fill="${t.accent}"/>
    <text x="42" y="27" fill="${t.accent}" font-size="19" font-weight="800" letter-spacing="1.5">${esc(modeTag)} · ${kind}</text>

    <text x="0" y="108" fill="#ffffff" font-size="66" font-weight="900" letter-spacing="-1">${esc(d.symbol)}</text>
    <text x="${Math.min(560, d.symbol.length * 40 + 14)}" y="108" fill="#64748b" font-size="40" font-weight="700">/SOL</text>

    <text x="0" y="270" fill="url(#pct)" font-size="150" font-weight="900" letter-spacing="-4">${pctStr(d.pnlPct)}</text>

    <text x="2" y="352" fill="#7c8aa5" font-size="24" font-weight="600">Başlangıç</text>
    <text x="230" y="352" fill="#cbd5e1" font-size="26" font-weight="800">${sol(d.initialSol)}</text>
    <text x="2" y="398" fill="#7c8aa5" font-size="24" font-weight="600">Güncel</text>
    <text x="230" y="398" fill="${t.accent}" font-size="26" font-weight="800">${sol(d.worthSol)}</text>

    <rect x="0" y="430" width="${t.label.length * 20 + 70}" height="52" rx="14" fill="${t.accent}" opacity="0.16"/>
    <text x="24" y="465" font-size="30" font-weight="900" fill="${t.accent}">${t.emoji} ${esc(t.label)}</text>
  </g>

  <!-- Mascot -->
  <circle cx="960" cy="300" r="180" fill="#0b1220" stroke="${t.accent}" stroke-width="4" opacity="0.95"/>
  <circle cx="960" cy="300" r="180" fill="none" stroke="${t.accent}" stroke-width="10" opacity="0.25"/>
  <text x="960" y="360" text-anchor="middle" font-size="200">${t.emoji}</text>

  <!-- Alt bar -->
  <rect x="0" y="${H - 72}" width="${W}" height="72" fill="#0b1220" opacity="0.85"/>
  <text x="64" y="${H - 28}" fill="#e2e8f0" font-size="26" font-weight="900" letter-spacing="0.5">ALTAY · AI Trade Panel</text>
  <text x="${W - 64}" y="${H - 28}" text-anchor="end" fill="#64748b" font-size="20" font-weight="600">${esc(dateStr)}</text>
</svg>`;
}

/** SVG'yi PNG'ye çevirip indirir (canvas; bağımlılıksız). */
export async function downloadTradeCardPng(d: TradeCardData, filename = "islem-karti.png") {
  const svg = buildTradeCardSVG(d);
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.decoding = "async";
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error("SVG yüklenemedi"));
      img.src = url;
    });
    const scale = 2; // retina
    const canvas = document.createElement("canvas");
    canvas.width = W * scale; canvas.height = H * scale;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, W, H);
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
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Ekranda kartı gösteren React sarmalayıcı. */
export function TradeShareCard({ data, className }: { data: TradeCardData; className?: string }) {
  const svg = useMemo(() => buildTradeCardSVG(data), [data]);
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={ref}
      className={className}
      style={{ width: "100%", aspectRatio: `${W} / ${H}`, borderRadius: 16, overflow: "hidden" }}
      // buildTradeCardSVG çıktısı kontrollüdür (kullanıcı metni esc'lenir).
      dangerouslySetInnerHTML={{ __html: svg }}
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

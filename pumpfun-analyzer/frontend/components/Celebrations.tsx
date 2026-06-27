"use client";
import { useEffect, useRef } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { useToast } from "./Toast";

// ---- hafif konfeti (canvas, bağımlılıksız, kendini temizler) ----
function burstConfetti(power = 1) {
  if (typeof document === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const cv = document.createElement("canvas");
  cv.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:9999";
  cv.width = window.innerWidth; cv.height = window.innerHeight;
  document.body.appendChild(cv);
  const ctx = cv.getContext("2d")!;
  const colors = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#34d399", "#f472b6"];
  const N = Math.round(90 * power);
  const parts = Array.from({ length: N }, () => ({
    x: cv.width / 2 + (Math.random() - 0.5) * 220,
    y: cv.height * 0.32 + (Math.random() - 0.5) * 60,
    vx: (Math.random() - 0.5) * 9,
    vy: Math.random() * -11 - 4,
    g: 0.28 + Math.random() * 0.18,
    s: 5 + Math.random() * 6,
    rot: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3,
    c: colors[(Math.random() * colors.length) | 0], life: 0,
  }));
  const start = performance.now();
  const tick = (now: number) => {
    const t = now - start;
    ctx.clearRect(0, 0, cv.width, cv.height);
    parts.forEach((p) => {
      p.vy += p.g; p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.life = t;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.globalAlpha = Math.max(0, 1 - t / 2600);
      ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6);
      ctx.restore();
    });
    if (t < 2600) requestAnimationFrame(tick);
    else cv.remove();
  };
  requestAnimationFrame(tick);
}

function flashShake(kind: "loss") {
  if (typeof document === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const el = document.createElement("div");
  el.className = "screen-flash-loss";
  document.body.appendChild(el);
  document.body.classList.add("shake-x");
  setTimeout(() => { el.remove(); document.body.classList.remove("shake-x"); }, 700);
}

// ---- ping sesi (WebAudio; localStorage ile aç/kapa) ----
export function playPing() {
  try {
    if (typeof window === "undefined") return;
    if (localStorage.getItem("altay_sound") !== "1") return;
    const AC = (window.AudioContext || (window as any).webkitAudioContext);
    if (!AC) return;
    const ac = new AC();
    const o = ac.createOscillator(); const g = ac.createGain();
    o.type = "sine"; o.frequency.value = 880;
    o.connect(g); g.connect(ac.destination);
    g.gain.setValueAtTime(0.0001, ac.currentTime);
    g.gain.exponentialRampToValueAtTime(0.12, ac.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.32);
    o.start(); o.stop(ac.currentTime + 0.34);
  } catch { /* sessizce yut */ }
}

/** Performans/işlem akışını izler; kâr kapanışında konfeti, zararda kırmızı
 *  titreşim, yeni pozisyon açılışında bildirim + (açıksa) ping. Shell içinde
 *  bir kez monte edilir. */
export function Celebrations() {
  const toast = useToast();
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 10000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 10000 });

  const prevClosed = useRef<number | null>(null);
  const prevPnl = useRef<number | null>(null);
  const prevOpen = useRef<number | null>(null);

  useEffect(() => {
    if (!perf) return;
    const closed = perf.closed_trades ?? 0;
    const pnl = perf.total_pnl_sol ?? 0;
    if (prevClosed.current !== null && closed > prevClosed.current) {
      const delta = pnl - (prevPnl.current ?? pnl);
      if (delta > 0) {
        burstConfetti(delta > 0.1 ? 2.2 : 1);     // büyük kazanç => daha çok konfeti
        toast("success", `İşlem kârla kapandı: +${delta.toFixed(4)} SOL 🎉`);
        playPing();
      } else if (delta < 0) {
        flashShake("loss");
        toast("error", `İşlem zararla kapandı: ${delta.toFixed(4)} SOL`);
      }
    }
    prevClosed.current = closed;
    prevPnl.current = pnl;
  }, [perf, toast]);

  useEffect(() => {
    if (!sum) return;
    const open = sum.open_positions ?? 0;
    if (prevOpen.current !== null && open > prevOpen.current) {
      toast("info", "Yeni pozisyon açıldı ⚡");
      playPing();
    }
    prevOpen.current = open;
  }, [sum, toast]);

  return null;
}

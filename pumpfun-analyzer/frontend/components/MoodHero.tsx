"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { BrandMark } from "./BrandMark";
import { CountUp } from "./CountUp";
import { Flame, Snowflake, Scale, Target, Layers, Coins, TrendingUp } from "lucide-react";

type Mood = "fire" | "frost" | "calm";

// Sabit (deterministik) parçacık konumları — SSR/hydration uyumlu, rastgele yok.
const FLAMES = [8, 22, 35, 50, 64, 78, 91];
const EMBERS = Array.from({ length: 14 }, (_, i) => i);
const SNOW = Array.from({ length: 18 }, (_, i) => i);

export function MoodHero() {
  const { data: ov } = useSWR<any>("/stats/overview", fetcher, { refreshInterval: 15000 });
  const { data: perf } = useSWR<any>("/stats/performance", fetcher, { refreshInterval: 30000 });
  const { data: sum } = useSWR<any>("/stats/trading-summary", fetcher, { refreshInterval: 15000 });

  const pnl = ov ? ov.pnl.paper_sol : 0;
  const mood: Mood = pnl > 0.0005 ? "fire" : pnl < -0.0005 ? "frost" : "calm";
  const up = pnl >= 0;
  const pnlColor = mood === "fire" ? "var(--emerald)" : mood === "frost" ? "var(--rose)" : "var(--brand)";

  const headline =
    mood === "fire" ? "Portföy yanıyor" : mood === "frost" ? "Soğuk dönem" : "Başabaş";
  const MoodIcon = mood === "fire" ? Flame : mood === "frost" ? Snowflake : Scale;
  const sub =
    mood === "fire" ? "Kopya stratejisi kâr üretiyor — akıllı parayı izlemeye devam."
    : mood === "frost" ? "Şu an zarardayız. Kaybettiren cüzdanlar otomatik eleniyor, kazandıranlar kalıyor."
    : "Henüz net sonuç yok. İşlemler kapandıkça portföy şekillenecek.";

  return (
    <div className={`mood-hero mb-5 mood-${mood}`}>
      <div className="mood-bg" />
      {/* parçacık katmanı */}
      <div className="mood-particles">
        {mood === "fire" && <>
          {FLAMES.map((l, i) => (
            <span key={`f${i}`} className="flame"
              style={{ left: `${l}%`, animationDelay: `${(i % 5) * 0.18}s`,
                       width: 50 + (i % 3) * 26, height: 80 + (i % 3) * 32, opacity: 0.9 }} />
          ))}
          {EMBERS.map((i) => (
            <span key={`e${i}`} className="ember"
              style={{ left: `${(i * 7 + 4) % 100}%`, animationDuration: `${2.4 + (i % 5) * 0.5}s`,
                       animationDelay: `${(i % 7) * 0.4}s` }} />
          ))}
        </>}
        {mood === "frost" && SNOW.map((i) => (
          <span key={`s${i}`} className="snow"
            style={{ left: `${(i * 5.5 + 3) % 100}%`, animationDuration: `${4 + (i % 5) * 0.8}s`,
                     animationDelay: `${(i % 9) * 0.5}s` }} />
        ))}
      </div>

      <div className="relative flex flex-wrap items-center justify-between gap-5">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold"
            style={{ borderColor: `color-mix(in srgb, ${pnlColor} 45%, var(--border))`, color: pnlColor }}>
            <BrandMark size={16} /> Altay Analysis Bot
          </div>
          <h1 className="flex items-center gap-2 text-3xl font-extrabold tracking-tight">
            <MoodIcon size={26} style={{ color: mood === "fire" ? "#f97316" : mood === "frost" ? "var(--sky)" : "var(--brand)" }} />
            <span>{headline}</span>
          </h1>
          <p className="mt-1 max-w-md text-sm muted">{sub}</p>

          <div className="mt-4 flex flex-wrap gap-2">
            <span className="hchip"><Target size={14} className="brand" />
              Başarı <b style={{ color: "var(--text)" }}>%{perf ? Math.round((perf.win_rate || 0) * 100) : "—"}</b></span>
            <span className="hchip"><TrendingUp size={14} className="brand" />
              {perf?.closed_trades ?? "—"} kapanmış</span>
            <span className="hchip"><Layers size={14} className="brand" />
              {sum?.open_positions ?? "—"} açık pozisyon</span>
            <span className="hchip"><Coins size={14} className="brand" />
              {ov?.wallets?.tracked ?? "—"} takip cüzdanı</span>
          </div>
        </div>

        <div className="text-right">
          <div className="text-xs font-medium muted">Toplam Paper PnL</div>
          <div className="pnl-figure text-5xl font-black" style={{ color: pnlColor }}>
            {ov ? <CountUp value={pnl} decimals={3} signed /> : "—"}
            <span className="ml-1 text-xl font-bold">SOL</span>
          </div>
          {sum && (
            <div className="mt-1 text-xs muted">
              Bugün: <b style={{ color: sum.today_realized_pnl_sol >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                {sum.today_realized_pnl_sol >= 0 ? "+" : ""}{sum.today_realized_pnl_sol} SOL</b>
              {" · "}açık risk {sum.open_exposure_sol} SOL
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

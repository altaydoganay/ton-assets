"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";

export type TokenMeta = { mint: string; name?: string | null; symbol?: string | null; image_url?: string | null; score?: number | null };

/** Bir grup mint için toplu görsel/kimlik verisi (avatar + ad + sembol). */
export function useTokenMeta(mints: (string | null | undefined)[]): Record<string, TokenMeta> {
  const uniq = Array.from(new Set(mints.filter(Boolean) as string[])).sort();
  const key = uniq.length ? `/tokens/meta?mints=${encodeURIComponent(uniq.join(","))}` : null;
  const { data } = useSWR<Record<string, TokenMeta>>(key, fetcher, { refreshInterval: 60000, revalidateOnFocus: false });
  return data || {};
}

function hashHue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

/**
 * Token avatarı: piyasa resmi varsa gösterir; yoksa mint'ten türetilen renkli
 * gradient daire + sembol/mint baş harfleri. Resim yüklenemezse otomatik fallback.
 */
export function TokenAvatar({ mint, meta, size = 34 }: { mint?: string | null; meta?: TokenMeta; size?: number }) {
  const [broken, setBroken] = useState(false);
  const m: TokenMeta = meta || { mint: mint || "" };
  const img = m.image_url;
  const label = (m.symbol || m.name || mint || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  const hue = hashHue(mint || label);
  const dim = { width: size, height: size };

  if (img && !broken) {
    return (
      <img
        src={img}
        alt={m.symbol || "token"}
        width={size}
        height={size}
        onError={() => setBroken(true)}
        className="shrink-0 rounded-full object-cover"
        style={{ ...dim, border: "1px solid var(--border)", background: "var(--bg2)" }}
      />
    );
  }
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full font-bold text-white"
      style={{
        ...dim,
        fontSize: size * 0.36,
        background: `linear-gradient(135deg, hsl(${hue} 70% 52%), hsl(${(hue + 40) % 360} 72% 46%))`,
        border: "1px solid color-mix(in srgb, black 12%, transparent)",
      }}
      title={m.name || mint || ""}
    >
      {label}
    </div>
  );
}

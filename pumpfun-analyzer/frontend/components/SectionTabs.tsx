"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";

/**
 * Bölüm sekmeleri: birbiriyle ilişkili sayfaları tek "hub" gibi gösterir.
 * Rotalar korunur (hiçbir işlev taşınmaz/silinmez); yalnızca gezinme birleşir.
 */
type Tab = { href: string; label: string };

const GROUPS: Record<string, Tab[]> = {
  portfolio: [
    { href: "/positions", label: "Açık Pozisyonlar" },
    { href: "/history", label: "Geçmiş" },
    { href: "/paper", label: "Paper Detay" },
    { href: "/live", label: "Canlı Detay" },
    { href: "/performance", label: "Performans" },
  ],
  tokens: [
    { href: "/tokens", label: "Token Analizi" },
    { href: "/tokens/tracked", label: "İzlenen Tokenler" },
    { href: "/events", label: "Olay Akışı" },
  ],
  wallets: [
    { href: "/wallets/leaderboard", label: "Sıralama" },
    { href: "/wallets/discovered", label: "Keşfedilen" },
    { href: "/wallets/tracked", label: "Takip Edilen" },
    { href: "/events", label: "Olay Akışı" },
  ],
  settings: [
    { href: "/settings/risk", label: "Strateji & Risk" },
    { href: "/settings/api", label: "Skorlama" },
    { href: "/settings/live", label: "Canlı Kurulum" },
    { href: "/health", label: "Sistem Sağlığı" },
    { href: "/logs", label: "Teknik Loglar" },
  ],
};

export function SectionTabs({ group }: { group: keyof typeof GROUPS | "auto-events" }) {
  const pathname = usePathname();
  // /events her iki keşif grubunda da var; aktif moda göre doğru seti göster.
  const { data: risk } = useSWR<any>(group === "auto-events" ? "/settings/risk" : null, fetcher);
  const resolved: Tab[] =
    group === "auto-events"
      ? GROUPS[(risk?.value?.strategy_mode || "copy") === "ai" ? "tokens" : "wallets"]
      : GROUPS[group];

  return (
    <div className="mb-4 flex flex-wrap gap-1 rounded-2xl border p-1"
      style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--bg2) 55%, transparent)" }}>
      {resolved.map((t) => {
        const active = pathname === t.href || (t.href !== "/" && pathname.startsWith(t.href + "/"));
        return (
          <Link key={t.href} href={t.href}
            className={`rounded-xl px-3 py-1.5 text-sm font-semibold transition ${active ? "text-white" : "muted hover:opacity-100"}`}
            style={active ? { background: "var(--brand)" } : undefined}>
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}

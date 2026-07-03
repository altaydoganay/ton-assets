"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import clsx from "clsx";
import {
  LayoutDashboard, Search, Star, Coins, BadgeCheck, Activity, Bell, FlaskConical,
  Zap, Wallet, History, ShieldAlert, Server, HeartPulse, ScrollText, LineChart,
  Rocket, Menu, X, Trophy, Radio, BrainCircuit, CopyCheck, SlidersHorizontal,
  ShieldCheck, Gauge, HelpCircle,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { ListenerStatus } from "./ListenerStatus";
import { BrandLockup } from "./BrandMark";
import { Celebrations } from "./Celebrations";
import { SoundToggle } from "./SoundToggle";
import { WalletConnect } from "./WalletConnect";
import { CommandPalette, NotificationCenter, PremiumBackdrop, StatusStrip } from "./PremiumUI";
import { EmergencyStop } from "./EmergencyStop";
import { apiSend, fetcher } from "@/lib/api";
import { useToast } from "./Toast";

type Mode = "ai" | "copy";
type NavItem = { href: string; label: string; icon: any; desc?: string; match?: string[] };
type NavGroup = { group: string; items: NavItem[] };

// SADELEŞTİRİLMİŞ MENÜ: 5 ana bölüm. İlişkili sayfalar bölüm İÇİNDE sekmelerle
// gezilir (SectionTabs) — "birbiriyle alakalı şeyler farklı sekmelerde" karmaşası
// biter. Hiçbir sayfa silinmedi; hepsi kendi hub'ının sekmesi oldu.
const PORTFOLIO_MATCH = ["/positions", "/history", "/paper", "/live", "/performance"];
const SETTINGS_MATCH = ["/settings", "/health", "/logs"];

const COPY_NAV: NavGroup[] = [
  { group: "Menü", items: [
    { href: "/overview", label: "Genel Bakış", icon: LayoutDashboard },
    { href: "/copy", label: "Copy Merkezi", icon: CopyCheck, desc: "Karar akışı, performans ve ölçüm dönemi" },
    { href: "/positions", label: "Portföy", icon: Wallet, desc: "Pozisyonlar · Geçmiş · Performans · Sıfırlama", match: PORTFOLIO_MATCH },
    { href: "/wallets/leaderboard", label: "Cüzdan Keşfi", icon: Trophy, desc: "Sıralama · Keşfedilen · Takip · Olay akışı", match: ["/wallets", "/events"] },
    { href: "/settings/risk", label: "Ayarlar", icon: SlidersHorizontal, desc: "Risk · Skorlama · Canlı kurulum · Sağlık · Loglar", match: SETTINGS_MATCH },
  ]},
];

const AI_NAV: NavGroup[] = [
  { group: "Menü", items: [
    { href: "/overview", label: "Genel Bakış", icon: LayoutDashboard },
    { href: "/ai", label: "AI Merkezi", icon: BrainCircuit, desc: "Karne, karar akışı ve huni" },
    { href: "/positions", label: "Portföy", icon: Wallet, desc: "Pozisyonlar · Geçmiş · Performans · Sıfırlama", match: PORTFOLIO_MATCH },
    { href: "/tokens", label: "Token Keşfi", icon: Coins, desc: "Analiz · İzlenen · Olay akışı", match: ["/tokens", "/events"] },
    { href: "/settings/risk", label: "Ayarlar", icon: SlidersHorizontal, desc: "Risk · Skorlama · Canlı kurulum · Sağlık · Loglar", match: SETTINGS_MATCH },
  ]},
];

function modeCopy(mode: Mode) {
  if (mode === "ai") {
    return {
      title: "AI TRADE",
      subtitle: "Token fırsat motoru",
      desc: "Copy motoru tamamen durur. Kararı otomatik AI token profili verir.",
      icon: BrainCircuit,
      tone: "var(--violet)",
    };
  }
  return {
    title: "COPY TRADE",
    subtitle: "Cüzdan kopyalama motoru",
    desc: "AI token motoru durur. Copyability, sniper filtresi ve leader-watch aktif.",
    icon: CopyCheck,
    tone: "var(--emerald)",
  };
}

function ModeMiniCard({ mode, risk, mutate }: { mode: Mode; risk: any; mutate: () => void }) {
  const toast = useToast();
  const cfg = modeCopy(mode);
  const Icon = cfg.icon;
  async function setMode(next: Mode) {
    if (!risk?.value) return toast("info", "Ayarlar yükleniyor");
    try {
      await apiSend("/settings/risk", "PUT", { value: { ...risk.value, strategy_mode: next } });
      await mutate();
      toast("success", `${next === "ai" ? "AI TRADE" : "COPY TRADE"} aktif`);
    } catch (e: any) { toast("error", e?.message || "Mod değiştirilemedi"); }
  }
  return (
    <div className="mode-mini-card mb-4">
      <div className="flex items-start gap-3">
        <div className="mode-mini-icon" style={{ color: cfg.tone, background: `color-mix(in srgb, ${cfg.tone} 14%, transparent)` }}><Icon size={18} /></div>
        <div className="min-w-0 flex-1">
          <div className="text-xs muted">Aktif çalışma modu</div>
          <div className="flex items-center gap-2 font-extrabold tracking-tight">{cfg.title}</div>
          <div className="mt-0.5 text-[11px] muted leading-relaxed">{cfg.desc}</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button className={mode === "ai" ? "mode-pill active" : "mode-pill"} onClick={() => setMode("ai")}>AI</button>
        <button className={mode === "copy" ? "mode-pill active" : "mode-pill"} onClick={() => setMode("copy")}>Copy</button>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { data: risk, mutate } = useSWR<any>("/settings/risk", fetcher, { refreshInterval: 12000 });
  const mode = ((risk?.value?.strategy_mode || "copy") as Mode);
  const navGroups = mode === "ai" ? AI_NAV : COPY_NAV;
  const cfg = modeCopy(mode);
  const HeaderIcon = cfg.icon;

  const nav = (
    <nav className="space-y-4">
      <ModeMiniCard mode={mode} risk={risk} mutate={() => mutate()} />
      {navGroups.map((g) => (
        <div key={g.group}>
          <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider muted">{g.group}</div>
          <div className="space-y-0.5">
            {g.items.map((item) => {
              const Icon = item.icon;
              // Hub eşleşmesi: alt sayfalar (örn. /history) kendi hub'ını
              // (Portföy) aktif gösterir — match listesi varsa ona bakılır.
              const prefixes = item.match ?? [item.href];
              const active = item.href === "/overview"
                ? pathname === "/" || pathname.startsWith("/overview")
                : prefixes.some((p) => pathname === p || pathname.startsWith(p + "/"));
              return (
                <Link key={item.href} href={item.href} onClick={() => setOpen(false)}
                  className={clsx("nav-link", active && "active")}
                  title={item.desc || item.label}>
                  <Icon size={16} /><span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  return (
    <div className={`premium-shell ${mode === "ai" ? "mode-ai" : "mode-copy"}`}>
      <PremiumBackdrop />
      <div className="flex h-screen overflow-hidden relative z-10">
      <aside className="premium-sidebar hidden w-72 shrink-0 flex-col border-r p-3 md:flex">
        <div className="mb-4 px-1 pt-1">
          <BrandLockup size={34} />
        </div>
        <div className="flex-1 overflow-y-auto pr-1">{nav}</div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-80 overflow-y-auto p-3" style={{ background: "var(--bg2)" }}>
            <div className="mb-4 flex items-center justify-between px-1">
              <BrandLockup size={32} subtitle={false} />
              <button className="btn-ghost" onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="premium-topbar flex items-center justify-between border-b px-4 py-3 md:px-6">
          <div className="flex items-center gap-3">
            <button className="btn-ghost md:hidden" onClick={() => setOpen(true)}><Menu size={20} /></button>
            <div className="hidden items-center gap-2 rounded-2xl border px-3 py-2 sm:flex" style={{ background: "var(--bg2)", borderColor: "var(--border)" }}>
              <HeaderIcon size={16} style={{ color: cfg.tone }} />
              <div>
                <div className="text-xs font-bold leading-none">{cfg.title}</div>
                <div className="mt-0.5 text-[10px] muted leading-none">{risk?.value?.mode || "paper"} mod · {risk?.value?.enabled ? "motor açık" : "motor kapalı"}</div>
              </div>
            </div>
            <ListenerStatus />
            <div className="hidden lg:block"><CommandPalette /></div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs muted xl:inline">Kâr garantisi yok · küçük bakiye ve paper doğrulama önerilir</span>
            <EmergencyStop risk={risk} onChange={() => mutate()} />
            <span className="badge hidden sm:inline-flex">UI 98</span>
            <NotificationCenter />
            <WalletConnect />
            <SoundToggle />
            <ThemeToggle />
          </div>
        </header>
        {risk?.value?.emergency_stop && (
          <div className="flex items-center justify-center gap-2 border-b bg-red-500/10 px-4 py-2 text-xs font-semibold text-red-500"
               style={{ borderColor: "var(--border)" }}>
            <ShieldAlert size={14} /> ACİL DURDURMA ETKİN — yeni alımlar durduruldu. Sağ üstten "Devam Et" ile açabilirsin.
          </div>
        )}
        <StatusStrip />
        <main className="premium-main flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
        <Celebrations />
      </div>
    </div>
  </div>
  );
}

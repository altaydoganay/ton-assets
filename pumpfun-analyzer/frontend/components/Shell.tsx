"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  LayoutDashboard, Search, Star, Coins, BadgeCheck, Activity, Bell, FlaskConical,
  Zap, Wallet, History, ShieldAlert, Server, HeartPulse, ScrollText, LineChart,
  Rocket, Menu, X, Trophy, Radio,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { ListenerStatus } from "./ListenerStatus";

const NAV = [
  { group: "Genel", items: [
    { href: "/", label: "Genel Bakış", icon: LayoutDashboard },
    { href: "/setup", label: "Kurulum & Sağlık", icon: Rocket },
    { href: "/performance", label: "Performans", icon: LineChart },
  ]},
  { group: "Cüzdanlar", items: [
    { href: "/wallets/leaderboard", label: "Cüzdan Sıralaması", icon: Trophy },
    { href: "/wallets/discovered", label: "Keşfedilen Cüzdanlar", icon: Search },
    { href: "/wallets/tracked", label: "Takip Edilen Cüzdanlar", icon: Star },
  ]},
  { group: "Tokenler", items: [
    { href: "/tokens", label: "Token Analizi", icon: Coins },
    { href: "/tokens/tracked", label: "Token Performansı", icon: BadgeCheck },
  ]},
  { group: "İşlemler", items: [
    { href: "/events", label: "Canlı Olay Akışı", icon: Activity },
    { href: "/alerts", label: "Telegram Bildirimleri", icon: Bell },
    { href: "/paper", label: "Paper Trading", icon: FlaskConical },
    { href: "/live", label: "Canlı İşlemler", icon: Zap },
    { href: "/positions", label: "Açık Pozisyonlar", icon: Wallet },
    { href: "/history", label: "İşlem Geçmişi", icon: History },
  ]},
  { group: "Ayarlar", items: [
    { href: "/settings/risk", label: "Risk Ayarları", icon: ShieldAlert },
    { href: "/settings/live", label: "Canlı İşlem Kurulumu", icon: Radio },
    { href: "/settings/api", label: "API ve RPC Ayarları", icon: Server },
    { href: "/health", label: "Sistem Sağlığı", icon: HeartPulse },
    { href: "/logs", label: "Loglar", icon: ScrollText },
  ]},
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const nav = (
    <nav className="space-y-4">
      {NAV.map((g) => (
        <div key={g.group}>
          <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider muted">{g.group}</div>
          <div className="space-y-0.5">
            {g.items.map((item) => {
              const Icon = item.icon;
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link key={item.href} href={item.href} onClick={() => setOpen(false)}
                  className={clsx("nav-link", active && "active")}>
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
    <div className="flex h-screen overflow-hidden">
      {/* Masaüstü kenar çubuğu */}
      <aside className="hidden w-64 shrink-0 flex-col border-r p-3 md:flex" style={{ background: "var(--bg2)" }}>
        <div className="mb-4 px-2">
          <div className="text-lg font-bold brand">Pump.fun Analiz</div>
          <div className="text-xs muted">Cüzdan & Token İstihbaratı</div>
        </div>
        <div className="flex-1 overflow-y-auto">{nav}</div>
      </aside>

      {/* Mobil çekmece */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-72 overflow-y-auto p-3" style={{ background: "var(--bg2)" }}>
            <div className="mb-4 flex items-center justify-between px-2">
              <div className="text-lg font-bold brand">Pump.fun Analiz</div>
              <button className="btn-ghost" onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b px-4 py-3 md:px-6" style={{ background: "var(--card)" }}>
          <div className="flex items-center gap-3">
            <button className="btn-ghost md:hidden" onClick={() => setOpen(true)}><Menu size={20} /></button>
            <ListenerStatus />
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs muted sm:inline">Yatırım tavsiyesi değildir · Kârlılık garantisi yoktur</span>
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

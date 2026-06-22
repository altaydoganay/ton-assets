"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  LayoutDashboard, Search, Star, Coins, BadgeCheck, Activity, Bell,
  FlaskConical, Zap, Wallet, History, ShieldAlert, Server, HeartPulse, ScrollText,
} from "lucide-react";

const NAV = [
  { href: "/", label: "Genel Bakış", icon: LayoutDashboard },
  { href: "/wallets/discovered", label: "Keşfedilen Cüzdanlar", icon: Search },
  { href: "/wallets/tracked", label: "Takip Edilen Cüzdanlar", icon: Star },
  { href: "/tokens", label: "Token Analizi", icon: Coins },
  { href: "/tokens/tracked", label: "Takip Edilen Tokenler", icon: BadgeCheck },
  { href: "/events", label: "Canlı Olay Akışı", icon: Activity },
  { href: "/alerts", label: "Telegram Bildirimleri", icon: Bell },
  { href: "/paper", label: "Paper Trading", icon: FlaskConical },
  { href: "/live", label: "Canlı İşlemler", icon: Zap },
  { href: "/positions", label: "Açık Pozisyonlar", icon: Wallet },
  { href: "/history", label: "İşlem Geçmişi", icon: History },
  { href: "/settings/risk", label: "Risk Ayarları", icon: ShieldAlert },
  { href: "/settings/api", label: "API ve RPC Ayarları", icon: Server },
  { href: "/health", label: "Sistem Sağlığı", icon: HeartPulse },
  { href: "/logs", label: "Loglar", icon: ScrollText },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-64 shrink-0 border-r p-3 overflow-y-auto" style={{ borderColor: "var(--border)" }}>
      <div className="mb-4 px-2">
        <div className="text-lg font-bold text-brand">Pump.fun Analiz</div>
        <div className="text-xs muted">Cüzdan & Token İstihbaratı</div>
      </div>
      <nav className="space-y-0.5">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} className={clsx("nav-link", active && "active")}>
              <Icon size={16} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

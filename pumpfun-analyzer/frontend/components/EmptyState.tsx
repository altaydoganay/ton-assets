"use client";
import Link from "next/link";
import { Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** Animasyonlu, yönlendiren boş-durum kartı. */
export function EmptyState({
  icon: Icon = Inbox, title, hint, action, height = 200,
}: {
  icon?: LucideIcon; title: string; hint?: string;
  action?: { href: string; label: string }; height?: number;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center" style={{ minHeight: height }}>
      <div className="empty-orb mb-3 grid h-16 w-16 place-items-center rounded-2xl"
        style={{ background: "color-mix(in srgb, var(--brand) 12%, transparent)", color: "var(--brand)" }}>
        <Icon size={28} />
      </div>
      <div className="text-sm font-semibold">{title}</div>
      {hint && <div className="mt-1 max-w-xs text-xs muted">{hint}</div>}
      {action && <Link href={action.href} className="btn-primary mt-3 text-xs">{action.label}</Link>}
    </div>
  );
}

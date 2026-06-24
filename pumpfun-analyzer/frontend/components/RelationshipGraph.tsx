"use client";
import { shortAddr } from "@/lib/api";

type Rel = { source: string; target: string; kind: string; confidence: number };

const KIND_COLOR: Record<string, string> = {
  copy: "#f59e0b", insider: "#ef4444", funding: "#38bdf8", cluster: "#a78bfa",
};

/** Bağımlılıksız SVG ile basit ilişki grafiği (odak cüzdan + bağlı düğümler). */
export function RelationshipGraph({ center, rels }: { center: string; rels: Rel[] }) {
  if (!rels || rels.length === 0)
    return <p className="muted text-sm">Bağlantılı cüzdan tespit edilmedi.</p>;

  const others = rels.map((r) => (r.source === center ? r.target : r.source));
  const W = 520, H = 320, cx = W / 2, cy = H / 2, R = 110;
  const nodes = others.map((addr, i) => {
    const a = (2 * Math.PI * i) / others.length - Math.PI / 2;
    return { addr, x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), rel: rels[i] };
  });

  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H} className="mx-auto">
        {nodes.map((n, i) => (
          <line key={"e" + i} x1={cx} y1={cy} x2={n.x} y2={n.y}
            stroke={KIND_COLOR[n.rel.kind] || "var(--border)"} strokeWidth={1 + n.rel.confidence * 2} opacity={0.6} />
        ))}
        {nodes.map((n, i) => (
          <g key={"n" + i}>
            <circle cx={n.x} cy={n.y} r={20} fill="var(--card)" stroke={KIND_COLOR[n.rel.kind] || "var(--border)"} strokeWidth={2} />
            <text x={n.x} y={n.y + 34} textAnchor="middle" fontSize={9} fill="var(--muted)">{shortAddr(n.addr)}</text>
            <text x={n.x} y={n.y + 44} textAnchor="middle" fontSize={8} fill={KIND_COLOR[n.rel.kind]}>{n.rel.kind} %{Math.round(n.rel.confidence * 100)}</text>
          </g>
        ))}
        <circle cx={cx} cy={cy} r={26} fill="var(--brand)" opacity={0.25} />
        <circle cx={cx} cy={cy} r={22} fill="var(--card)" stroke="var(--brand)" strokeWidth={2} />
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize={9} fill="var(--text)">{shortAddr(center)}</text>
      </svg>
    </div>
  );
}

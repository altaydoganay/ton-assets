"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  RadarChart, PolarGrid, PolarAngleAxis, Radar,
} from "recharts";

export function SubScoreRadar({ data }: { data: { label: string; value: number }[] }) {
  const series = data.map((d) => ({ subject: d.label, A: d.value }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <RadarChart data={series} outerRadius="72%">
        <PolarGrid stroke="var(--border)" />
        <PolarAngleAxis dataKey="subject" tick={{ fill: "var(--muted)", fontSize: 10 }} />
        <Radar dataKey="A" stroke="#2dd4bf" fill="#2dd4bf" fillOpacity={0.35} />
        <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }} />
      </RadarChart>
    </ResponsiveContainer>
  );
}

export function ScoreChart({ data }: { data: { created_at: string; total: number }[] }) {
  const series = data.map((d) => ({
    t: new Date(d.created_at).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" }),
    Puan: d.total,
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={series}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="t" stroke="var(--muted)" fontSize={12} />
        <YAxis domain={[0, 100]} stroke="var(--muted)" fontSize={12} />
        <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }} />
        <Line type="monotone" dataKey="Puan" stroke="#14b8a6" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function SubScoreBars({ scores }: { scores: { label: string; value: number; weight: string }[] }) {
  return (
    <div className="space-y-2">
      {scores.map((s) => (
        <div key={s.label}>
          <div className="flex justify-between text-xs mb-0.5">
            <span>{s.label} <span className="muted">({s.weight})</span></span>
            <span className="font-medium">{s.value.toFixed(0)}/100</span>
          </div>
          <div className="h-2 rounded-full" style={{ background: "var(--border)" }}>
            <div
              className="h-2 rounded-full"
              style={{ width: `${s.value}%`, background: s.value >= 70 ? "#10b981" : s.value >= 50 ? "#f59e0b" : "#ef4444" }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

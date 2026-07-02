"use client";
import Link from "next/link";
import useSWR from "swr";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { Fetch } from "@/components/Fetch";
import { Callout } from "@/components/ui";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Turtle, Zap, Globe, Check } from "lucide-react";

// Veri akışı modları — iki bayrağın (listener + firehose/discovery) kombinasyonu.
type Mode = "poll" | "realtime" | "discover";
function currentMode(setup: any): Mode {
  if (!setup) return "realtime";
  if (setup.listener_enabled === false) return "poll";
  return setup.discovery_enabled ? "discover" : "realtime";
}

const MODES: { id: Mode; icon: any; title: string; cost: string; desc: string; rec?: boolean }[] = [
  { id: "poll", icon: Turtle, title: "Sadece POLL", cost: "En ucuz",
    desc: "Canlı dinleyici kapalı. Takip cüzdanları ~60 sn'de bir taranır. Gecikme yüksek (taze token'de tepeyi kaçırabilirsin) ama Helius streaming kredisi ≈0." },
  { id: "realtime", icon: Zap, title: "Gerçek-zaman kopya", cost: "Hızlı + ucuz", rec: true,
    desc: "Dinleyici açık, firehose KAPALI. Sadece TAKİP cüzdanlarına abone olunur → işlem yapar yapmaz (~saniyeler) yakalanır. Olay-bazlı: yalnızca gerçek işlemde kredi harcar (firehose maliyeti YOK). 60 sn POLL yedek olarak kalır." },
  { id: "discover", icon: Globe, title: "Gerçek-zaman + keşif", cost: "En pahalı",
    desc: "Dinleyici + firehose açık. Tüm pump.fun akışından YENİ cüzdan keşfedilir. Streaming kredisini en çok bu yakar — yalnızca yeni cüzdan havuzu ararken aç." },
];

export default function Events() {
  const { data: setup, mutate } = useSWR<any>("/setup", fetcher, { refreshInterval: 10000 });
  const toast = useToast();
  const mode = currentMode(setup);
  const live = setup?.listener_enabled !== false;

  async function setMode(m: Mode) {
    try {
      // listener: poll modunda kapalı, diğerlerinde açık. firehose: yalnızca discover'da açık.
      await apiSend(`/setup/listener?enabled=${m !== "poll"}`, "POST");
      await apiSend(`/setup/discovery?enabled=${m === "discover"}`, "POST");
      await mutate();
      const label = MODES.find((x) => x.id === m)?.title;
      toast("success", `Mod: ${label}. ~30 sn içinde uygulanır.`);
    } catch (e: any) { toast("error", e?.message || "Mod değiştirilemedi"); }
  }

  return (
    <div>
      <PageHeader title="Canlı Olay Akışı"
        subtitle="Veri akışı modunu seç — kopya işlem hızı vs. Helius kredisi dengesi." />
      <SectionTabs group="auto-events" />

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        {MODES.map((m) => {
          const active = mode === m.id;
          const Icon = m.icon;
          return (
            <button key={m.id} onClick={() => setMode(m.id)}
              className="card text-left transition"
              style={{ borderColor: active ? "var(--brand)" : "var(--border)", borderWidth: active ? 2 : 1,
                       boxShadow: active ? "0 0 0 3px color-mix(in srgb, var(--brand) 18%, transparent)" : undefined }}>
              <div className="flex items-center justify-between">
                <Icon size={18} className="brand" />
                <span className="badge" style={{ background: m.rec ? "color-mix(in srgb, var(--emerald) 16%, transparent)" : "var(--bg2)",
                                                  color: m.rec ? "var(--emerald)" : "var(--muted)" }}>
                  {m.rec ? "Önerilen" : m.cost}
                </span>
              </div>
              <div className="mt-2 flex items-center gap-1.5 font-semibold">
                {m.title}{active && <Check size={15} className="text-emerald-500" />}
              </div>
              <p className="mt-1 text-xs muted">{m.desc}</p>
            </button>
          );
        })}
      </div>

      <div className="mb-4">
        <Callout kind={mode === "discover" ? "warn" : "info"}>
          {mode === "poll" && "🐢 POLL modu: en düşük kredi, ama ~60 sn gecikme. Hız önemliyse 'Gerçek-zaman kopya'ya geç."}
          {mode === "realtime" && "⚡ Gerçek-zaman kopya: takip cüzdanları işlem yapar yapmaz kopyalanır; firehose kapalı olduğu için kredi yalnızca gerçek işlemlerde harcanır. Kredi kısıtındayken en mantıklı mod."}
          {mode === "discover" && "🌐 Keşif açık: en yüksek kredi tüketimi (tüm pump.fun akışı). Yeni cüzdan ararken aç, bulunca geri 'Gerçek-zaman kopya'ya al."}
        </Callout>
      </div>

      <Fetch<any[]> path="/events?limit=100" isEmpty={(d) => d.length === 0}
        emptyLabel={live ? "Henüz olay yok" : "Dinleyici kapalı — yeni canlı olay gelmiyor (kopya işlem POLL ile sürüyor)"}
        refreshInterval={live ? 8000 : 0}>
        {(rows) => (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left muted border-b" style={{ borderColor: "var(--border)" }}>
                <th className="pb-2">Zaman</th><th>Cüzdan</th><th>Token</th><th>Yön</th><th>SOL</th><th>Venue</th><th>Durum</th>
              </tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="border-b last:border-0" style={{ borderColor: "var(--border)" }}>
                    <td className="py-2 muted">{new Date(s.block_time).toLocaleString("tr-TR")}</td>
                    <td><Link href={`/wallets/${s.wallet_address}`} className="clickable">{shortAddr(s.wallet_address)}</Link></td>
                    <td><Link href={`/tokens/${s.token_mint}`} className="clickable">{shortAddr(s.token_mint)}</Link></td>
                    <td><span className={s.side === "buy" ? "text-emerald-500" : "text-red-500"}>{s.side === "buy" ? "Alım" : "Satım"}</span></td>
                    <td>{fmtNum(s.sol_amount, 4)}</td>
                    <td className="muted">{s.venue || "—"}</td>
                    <td className="muted">{s.confirmation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Fetch>
    </div>
  );
}

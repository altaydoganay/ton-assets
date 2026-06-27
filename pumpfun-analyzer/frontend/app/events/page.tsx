"use client";
import Link from "next/link";
import useSWR from "swr";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { Callout } from "@/components/ui";
import { fetcher, apiSend, shortAddr, fmtNum } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Radio, RadioTower } from "lucide-react";

export default function Events() {
  const { data: setup, mutate } = useSWR<any>("/setup", fetcher, { refreshInterval: 10000 });
  const toast = useToast();
  const on = setup?.listener_enabled !== false;

  async function toggle(next: boolean) {
    try {
      await apiSend(`/setup/listener?enabled=${next}`, "POST");
      await mutate();
      toast(next ? "info" : "success",
        next ? "Canlı dinleyici açıldı (kredi harcar)"
             : "Canlı dinleyici kapatıldı — kopya işlem POLL ile sürer, Helius streaming kredisi ≈0");
    } catch (e: any) { toast("error", e?.message || "Değiştirilemedi"); }
  }

  return (
    <div>
      <PageHeader title="Canlı Olay Akışı" subtitle="Zincir üstü tespit edilen gerçek swap işlemleri (transferler ayıklanır)"
        action={
          <button className={on ? "btn-danger" : "btn-primary"} onClick={() => toggle(!on)} disabled={!setup}>
            {on ? <><RadioTower size={15} /> Dinleyiciyi Kapat (kredi tasarrufu)</> : <><Radio size={15} /> Dinleyiciyi Aç</>}
          </button>
        } />

      <div className="mb-4">
        <Callout kind={on ? "warn" : "info"}>
          {on
            ? "📡 Canlı dinleyici AÇIK: pump.fun olayları gerçek-zamanlı akıyor (Helius streaming kredisi harcar). Kopya işlem için GEREKLİ DEĞİL — 60 sn'lik POLL zaten takip cüzdanlarının alım/satımını yakalıyor. Krediyi korumak için kapatabilirsin."
            : "🟢 Canlı dinleyici KAPALI: Helius streaming kredisi ≈0. Kopya işlem POLL ile sürüyor (takip cüzdanları her ~60 sn taranıyor). Bu sayfaya yeni canlı olay düşmez; takip işlemleri Performans/İşlemler'de görünür."}
        </Callout>
      </div>

      <Fetch<any[]> path="/events?limit=100" isEmpty={(d) => d.length === 0}
        emptyLabel={on ? "Henüz olay yok" : "Dinleyici kapalı — yeni canlı olay gelmiyor (kopya işlem POLL ile sürüyor)"}
        refreshInterval={on ? 8000 : 0}>
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

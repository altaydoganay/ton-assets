"use client";
import useSWR from "swr";
import { fetcher, apiSend, shortAddr } from "@/lib/api";
import { solscanTx } from "@/lib/links";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { ScoreBadge } from "@/components/ScoreBadge";
import { useToast } from "@/components/Toast";
import { ExternalLink, Send } from "lucide-react";

export default function Alerts() {
  const toast = useToast();
  const { mutate } = useSWR("/alerts?limit=100", fetcher);

  async function resend(id: number) {
    try {
      const r: any = await apiSend(`/alerts/${id}/resend`, "POST");
      toast(r.sent ? "success" : "info", r.sent ? "Bildirim yeniden gönderildi" : "Telegram kapalı/yapılandırılmamış");
      mutate();
    } catch (e: any) {
      toast("error", e?.message || "Gönderilemedi");
    }
  }

  return (
    <div>
      <PageHeader title="Telegram Bildirimleri" subtitle="Takipteki cüzdan, takipteki tokeni aldığında gönderilen bildirimler (dedup uygulanır)" />
      <Fetch<any[]> path="/alerts?limit=100" isEmpty={(d) => d.length === 0} emptyLabel="Henüz bildirim gönderilmedi" refreshInterval={10000}>
        {(rows) => (
          <div className="space-y-3">
            {rows.map((a) => (
              <div key={a.id} className="card">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-medium">{shortAddr(a.wallet_address)}</span>
                    <ScoreBadge score={a.wallet_score} />
                    <span className="muted">→</span>
                    <span className="font-medium">{shortAddr(a.token_mint)}</span>
                    <ScoreBadge score={a.token_score} />
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {a.auto_traded && <span className="badge bg-purple-500/15 text-purple-400">Oto işlem</span>}
                    <span className={a.sent ? "text-emerald-500" : "muted"}>{a.sent ? "Gönderildi" : "Beklemede"}</span>
                    {!a.sent && <button className="btn-ghost" onClick={() => resend(a.id)}><Send size={13} /> Tekrar gönder</button>}
                    <a className="btn-ghost" href={solscanTx(a.signature)} target="_blank" rel="noreferrer"><ExternalLink size={13} /> İşlem</a>
                  </div>
                </div>
                <div className="muted text-xs mt-2">{new Date(a.created_at).toLocaleString("tr-TR")} · tx: {shortAddr(a.signature)}</div>
              </div>
            ))}
          </div>
        )}
      </Fetch>
    </div>
  );
}

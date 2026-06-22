"use client";
import { PageHeader } from "@/components/Confidence";
import { Fetch } from "@/components/Fetch";
import { ScoreBadge } from "@/components/ScoreBadge";
import { shortAddr } from "@/lib/api";

export default function Alerts() {
  return (
    <div>
      <PageHeader title="Telegram Bildirimleri" subtitle="Takipteki cüzdan, takipteki tokeni aldığında gönderilen bildirimler (dedup uygulanır)" />
      <Fetch<any[]> path="/alerts?limit=100" isEmpty={(d) => d.length === 0} emptyLabel="Henüz bildirim gönderilmedi" refreshInterval={10000}>
        {(rows) => (
          <div className="space-y-3">
            {rows.map((a) => (
              <div key={a.id} className="card">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-medium">{shortAddr(a.wallet_address)}</span>
                    <ScoreBadge score={a.wallet_score} />
                    <span className="muted">→</span>
                    <span className="font-medium">{shortAddr(a.token_mint)}</span>
                    <ScoreBadge score={a.token_score} />
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {a.auto_traded && <span className="badge bg-purple-500/15 text-purple-400">Oto işlem</span>}
                    <span className={a.sent ? "text-emerald-500" : "muted"}>{a.sent ? "Gönderildi" : "Beklemede"}</span>
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

"use client";
import { PageHeader } from "@/components/Confidence";
import { TradeTable } from "@/components/TradeTable";
import { apiSend } from "@/lib/api";

export default function Live() {
  return (
    <div>
      <PageHeader
        title="Canlı İşlemler"
        subtitle="Gerçek zincir üstü işlemler — yalnızca panelde risk onayı verildiğinde ve ayrı bir trading cüzdanı tanımlandığında çalışır"
        action={
          <button
            className="btn-primary bg-red-600 hover:bg-red-700"
            onClick={() => apiSend("/trading/emergency-stop?close_positions=false", "POST").then(() => alert("Acil durdurma etkinleştirildi: yeni işlemler durduruldu."))}
          >
            ⛔ Acil Durdurma
          </button>
        }
      />
      <div className="card mb-4 border-amber-500/40">
        <p className="text-sm">
          ⚠️ Canlı işlem riskli olabilir. <strong>Ayrı ve düşük bakiyeli</strong> bir trading cüzdanı kullanın;
          ana cüzdanınızla işlem yapmayın. Özel anahtar şifreli keystore'da tutulur, asla arayüze/loglara gönderilmez.
          Kârlılık garantisi yoktur.
        </p>
      </div>
      <TradeTable path="/trading/live" emptyLabel="Henüz canlı işlem yok" live />
    </div>
  );
}

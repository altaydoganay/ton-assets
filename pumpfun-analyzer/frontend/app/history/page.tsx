"use client";
import { useState } from "react";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { ResetCenter } from "@/components/ResetCenter";
import { TradeTable } from "@/components/TradeTable";
import { TradeShareCard } from "@/components/TradeShareCard";
import { TradeCardModal } from "@/components/ShareTradeButton";
import { Share2 } from "lucide-react";

function ShareCardIntro() {
  const [demo, setDemo] = useState(false);
  return (
    <div className="card mb-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-semibold"><Share2 size={16} /> Kâr/Zarar Paylaşım Kartı</h2>
          <p className="text-xs muted mt-1">
            Her kapanan işlemin yanındaki <Share2 size={11} className="inline" /> düğmesiyle eğlenceli bir banner
            oluşturup PNG indirebilirsin. Görseller telifsizdir (emoji tabanlı kendi mizah kademelerimiz).
          </p>
        </div>
        <button className="btn" onClick={() => setDemo(true)}>Örneği gör</button>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <TradeShareCard data={{ symbol: "BARAWEK", pnlPct: 52.12, initialSol: 5.0, worthSol: 7.606, mode: "ai", kind: "paper" }} />
        <TradeShareCard data={{ symbol: "DEGEN", pnlPct: -23.4, initialSol: 1.0, worthSol: 0.766, mode: "ai", kind: "paper" }} />
      </div>
      {demo && (
        <TradeCardModal
          data={{ symbol: "MOON", pnlPct: 148.06, initialSol: 3.0, worthSol: 7.442, mode: "ai", kind: "paper", when: new Date().toISOString() }}
          onClose={() => setDemo(false)}
        />
      )}
    </div>
  );
}

export default function History() {
  return (
    <div>
      <PageHeader title="İşlem Geçmişi" subtitle="Tüm paper ve canlı işlemler tek ekranda. Sıfırlama işlemlerinin tek adresi de burasıdır." />
      <SectionTabs group="portfolio" />
      <ShareCardIntro />
      <h2 className="mb-2 font-semibold">Paper İşlemler</h2>
      <TradeTable path="/trading/paper" emptyLabel="Paper işlem geçmişi yok" />
      <h2 className="mb-2 mt-6 font-semibold">Canlı İşlemler</h2>
      <TradeTable path="/trading/live" emptyLabel="Canlı işlem geçmişi yok" live />
      <div className="mt-6"><ResetCenter /></div>
    </div>
  );
}

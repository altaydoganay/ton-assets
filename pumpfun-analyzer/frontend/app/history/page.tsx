"use client";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { ResetCenter } from "@/components/ResetCenter";
import { TradeTable } from "@/components/TradeTable";

export default function History() {
  return (
    <div>
      <PageHeader title="İşlem Geçmişi" subtitle="Tüm paper ve canlı işlemler tek ekranda. Sıfırlama işlemlerinin tek adresi de burasıdır." />
      <SectionTabs group="portfolio" />
      <h2 className="mb-2 font-semibold">Paper İşlemler</h2>
      <TradeTable path="/trading/paper" emptyLabel="Paper işlem geçmişi yok" />
      <h2 className="mb-2 mt-6 font-semibold">Canlı İşlemler</h2>
      <TradeTable path="/trading/live" emptyLabel="Canlı işlem geçmişi yok" live />
      <div className="mt-6"><ResetCenter /></div>
    </div>
  );
}

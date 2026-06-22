"use client";
import { PageHeader } from "@/components/Confidence";
import { TradeTable } from "@/components/TradeTable";

export default function Paper() {
  return (
    <div>
      <PageHeader title="Paper Trading" subtitle="Gerçek para kullanmadan simüle edilen kopya işlemler (varsayılan mod)" />
      <TradeTable path="/trading/paper" emptyLabel="Henüz paper işlem yok" />
    </div>
  );
}

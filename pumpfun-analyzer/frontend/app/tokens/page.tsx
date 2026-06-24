"use client";
import { PageHeader } from "@/components/Confidence";
import { TokenTable } from "@/components/TokenTable";
import { AddToken } from "@/components/AddToken";

export default function TokenAnalysis() {
  return (
    <div>
      <PageHeader
        title="Token Analizi"
        subtitle="Pump.fun tokenleri — bonding curve, holder dağılımı, güvenlik ve creator analizi"
      />
      <AddToken refreshPath="/tokens?limit=200" />
      <TokenTable path="/tokens?limit=200" emptyLabel="Henüz analiz edilmiş token yok" />
    </div>
  );
}

"use client";
import { PageHeader } from "@/components/Confidence";
import { WalletTable } from "@/components/WalletTable";

export default function DiscoveredWallets() {
  return (
    <div>
      <PageHeader
        title="Keşfedilen Cüzdanlar"
        subtitle="Davranışsal kaynaklardan keşfedilmiş, analiz aşamasındaki aday cüzdanlar"
      />
      <WalletTable path="/wallets?limit=200" emptyLabel="Henüz keşfedilmiş cüzdan yok" />
    </div>
  );
}

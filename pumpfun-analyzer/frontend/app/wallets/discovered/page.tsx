"use client";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { WalletTable } from "@/components/WalletTable";
import { AddWallet } from "@/components/AddWallet";

export default function DiscoveredWallets() {
  return (
    <div>
      <PageHeader
        title="Keşfedilen Cüzdanlar"
        subtitle="Davranışsal kaynaklardan keşfedilmiş, analiz aşamasındaki aday cüzdanlar"
      />
      <SectionTabs group="wallets" />
      <AddWallet refreshPath="/wallets?limit=200" />
      <WalletTable path="/wallets?limit=200" emptyLabel="Henüz keşfedilmiş cüzdan yok" />
    </div>
  );
}

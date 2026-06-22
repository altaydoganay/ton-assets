"use client";
import { PageHeader } from "@/components/Confidence";
import { WalletTable } from "@/components/WalletTable";

export default function TrackedWallets() {
  return (
    <div>
      <PageHeader
        title="Takip Edilen Cüzdanlar"
        subtitle="Puanı 70+ olan ve hiçbir kritik vetoya takılmayan, kalıcı takipteki cüzdanlar"
      />
      <WalletTable path="/wallets/tracked" emptyLabel="Henüz takip edilen cüzdan yok" />
    </div>
  );
}

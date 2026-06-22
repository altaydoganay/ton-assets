"use client";
import { PageHeader } from "@/components/Confidence";
import { TokenTable } from "@/components/TokenTable";

export default function TrackedTokens() {
  return (
    <div>
      <PageHeader
        title="Takip Edilen Tokenler"
        subtitle="Puanı 70+ olan ve hiçbir kritik vetoya takılmayan tokenler"
      />
      <TokenTable path="/tokens/tracked" emptyLabel="Henüz takip edilen token yok" />
    </div>
  );
}

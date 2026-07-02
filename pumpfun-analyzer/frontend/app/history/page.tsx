"use client";
import Link from "next/link";
import { ArrowRight, FlaskConical, Zap } from "lucide-react";
import { PageHeader } from "@/components/Confidence";
import { TradeTable } from "@/components/TradeTable";

export default function History() {
  return (
    <div>
      <PageHeader title="İşlem Geçmişi" subtitle="Tüm paper ve canlı işlemler tek ekranda. Sıfırlama/istatistik panelleri hızlı sekmelerde."
        action={
          <div className="flex gap-2">
            <Link href="/paper" className="btn text-xs"><FlaskConical size={13} /> Paper detay <ArrowRight size={12} /></Link>
            <Link href="/live" className="btn text-xs"><Zap size={13} /> Canlı detay <ArrowRight size={12} /></Link>
          </div>
        } />
      <h2 className="mb-2 font-semibold">Paper İşlemler</h2>
      <TradeTable path="/trading/paper" emptyLabel="Paper işlem geçmişi yok" />
      <h2 className="mb-2 mt-6 font-semibold">Canlı İşlemler</h2>
      <TradeTable path="/trading/live" emptyLabel="Canlı işlem geçmişi yok" live />
    </div>
  );
}

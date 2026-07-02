"use client";
import { PageHeader } from "@/components/Confidence";
import { SectionTabs } from "@/components/SectionTabs";
import { TradeTable } from "@/components/TradeTable";
import { Callout } from "@/components/ui";
import { apiSend } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";

export default function Live() {
  const toast = useToast();
  const { confirm, dialog } = useConfirm();

  async function emergency() {
    const choice = await confirm({
      title: "Acil Durdurma",
      body: "Yeni işlemler durdurulacak. (Açık pozisyonları kapatmak için Açık Pozisyonlar sayfasını kullan.)",
      confirmText: "Yeni işlemleri durdur", danger: true,
    });
    if (!choice) return;
    await apiSend("/trading/emergency-stop?close_positions=false", "POST");
    toast("info", "Acil durdurma etkinleştirildi");
  }

  return (
    <div>
      {dialog}
      <PageHeader title="Canlı İşlemler" subtitle="Gerçek zincir üstü işlemler — yalnızca Risk Ayarları'ndan canlı mod açıkken çalışır"
        action={<button className="btn-danger" onClick={emergency}>⛔ Acil Durdurma</button>} />
      <SectionTabs group="portfolio" />

      <div className="mb-4">
        <Callout kind="warn">
          Canlı işlem <b>gerçek para</b> kullanır. <b>Ayrı ve düşük bakiyeli</b> bir trading cüzdanı kullan; ana cüzdanınla işlem yapma.
          Özel anahtar PumpPortal tarafında kalır, loglara/DB'ye yazılmaz. Kârlılık garantisi yoktur.
        </Callout>
      </div>

      <TradeTable path="/trading/live" emptyLabel="Henüz canlı işlem yok" live />
    </div>
  );
}

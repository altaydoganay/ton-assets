"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Loading } from "@/components/States";

type Risk = Record<string, any>;

const FIELDS: { key: string; label: string; type: "number" | "bool" | "text"; hint?: string }[] = [
  { key: "mode", label: "İşlem Modu (paper / alerts_only / live)", type: "text" },
  { key: "enabled", label: "İşlem Motoru Aktif", type: "bool" },
  { key: "live_confirmed", label: "Canlı İşlem Riski Onaylandı", type: "bool", hint: "Canlı işlem için açıkça onay gerekir" },
  { key: "fixed_sol_amount", label: "İşlem Başına Sabit SOL", type: "number" },
  { key: "proportional", label: "Hedef Miktarına Orantılı Kopyalama", type: "bool" },
  { key: "proportional_factor", label: "Orantı Katsayısı", type: "number" },
  { key: "max_position_sol", label: "Maksimum Pozisyon (SOL)", type: "number" },
  { key: "max_daily_spend_sol", label: "Günlük Maksimum Harcama (SOL)", type: "number" },
  { key: "max_daily_loss_sol", label: "Günlük Maksimum Zarar (SOL)", type: "number" },
  { key: "max_slippage", label: "Maksimum Slippage (0-1)", type: "number" },
  { key: "priority_fee_sol", label: "Priority Fee (SOL)", type: "number" },
  { key: "min_wallet_score", label: "Minimum Cüzdan Puanı", type: "number" },
  { key: "min_token_score", label: "Minimum Token Puanı", type: "number" },
  { key: "max_open_positions_per_token", label: "Token Başına Maks. Açık Pozisyon", type: "number" },
  { key: "max_follow_lag_seconds", label: "Maksimum İzleme Gecikmesi (sn)", type: "number" },
  { key: "min_liquidity_sol", label: "Minimum Likidite (SOL)", type: "number" },
  { key: "close_mode", label: "Kısmi Satışta Davranış (proportional / full)", type: "text" },
];

export default function RiskSettings() {
  const { data, mutate } = useSWR<{ key: string; value: Risk }>("/settings/risk", fetcher);
  const [form, setForm] = useState<Risk | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data?.value) setForm(data.value); }, [data]);
  if (!form) return <Loading />;

  function set(k: string, v: any) { setForm({ ...form, [k]: v }); setSaved(false); }

  async function save() {
    await apiSend("/settings/risk", "PUT", { value: form });
    await mutate();
    setSaved(true);
  }

  return (
    <div>
      <PageHeader
        title="Risk Ayarları"
        subtitle="Kopya işlem ve risk limitleri. Tüm parametreler buradan değiştirilebilir."
        action={<button className="btn-primary" onClick={save}>Kaydet</button>}
      />
      {saved && <div className="card mb-4 border-emerald-500/40 text-emerald-500 text-sm">Ayarlar kaydedildi.</div>}
      {form.emergency_stop && <div className="card mb-4 border-red-500/40 text-red-500 text-sm">⛔ Acil durdurma etkin.</div>}

      <div className="card grid grid-cols-1 gap-4 md:grid-cols-2">
        {FIELDS.map((f) => (
          <div key={f.key}>
            <label className="text-sm">{f.label}</label>
            {f.hint && <div className="text-xs muted">{f.hint}</div>}
            {f.type === "bool" ? (
              <button className="btn mt-1" onClick={() => set(f.key, !form[f.key])}>
                {form[f.key] ? "Açık" : "Kapalı"}
              </button>
            ) : (
              <input
                className="input mt-1"
                type={f.type === "number" ? "number" : "text"}
                step="any"
                value={form[f.key] ?? ""}
                onChange={(e) => set(f.key, f.type === "number" ? parseFloat(e.target.value) : e.target.value)}
              />
            )}
          </div>
        ))}
      </div>

      <div className="card mt-4">
        <h2 className="font-semibold mb-2">Engelleme Listeleri</h2>
        <p className="text-xs muted mb-2">Virgülle ayrılmış adresler.</p>
        <label className="text-sm">Engellenen Cüzdanlar</label>
        <input className="input mt-1 mb-3" value={(form.blocked_wallets || []).join(",")}
          onChange={(e) => set("blocked_wallets", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
        <label className="text-sm">Engellenen Tokenler</label>
        <input className="input mt-1 mb-3" value={(form.blocked_tokens || []).join(",")}
          onChange={(e) => set("blocked_tokens", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
        <label className="text-sm">Yalnızca Bu Cüzdanları Kopyala (boşsa tümü)</label>
        <input className="input mt-1" value={(form.only_wallets || []).join(",")}
          onChange={(e) => set("only_wallets", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
      </div>
    </div>
  );
}

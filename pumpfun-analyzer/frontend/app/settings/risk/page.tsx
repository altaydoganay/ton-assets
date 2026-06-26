"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, Callout } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";
import { Loading } from "@/components/States";
import { Shield, Scale, Flame, Save } from "lucide-react";

type Risk = Record<string, any>;

const FIELDS: { key: string; label: string; type: "number" | "bool" | "text"; hint?: string }[] = [
  { key: "mode", label: "İşlem Modu", type: "text", hint: "paper (simülasyon) / alerts_only (sadece bildirim) / live (gerçek)" },
  { key: "enabled", label: "İşlem Motoru Aktif", type: "bool", hint: "Kapalıyken hiçbir işlem yapılmaz" },
  { key: "fixed_sol_amount", label: "İşlem Başına SOL", type: "number", hint: "Her kopya alımında harcanacak sabit miktar" },
  { key: "proportional", label: "Orantılı Kopyalama", type: "bool", hint: "Hedef cüzdanın miktarına oranla al" },
  { key: "max_position_sol", label: "Maksimum Pozisyon (SOL)", type: "number" },
  { key: "max_daily_spend_sol", label: "Günlük Maks. Harcama (SOL)", type: "number", hint: "Bu limite ulaşınca yeni alım durur" },
  { key: "max_daily_loss_sol", label: "Günlük Maks. Zarar (SOL)", type: "number", hint: "Bu zarara ulaşınca işlem durur" },
  { key: "max_slippage", label: "Maksimum Slippage", type: "number", hint: "0.15 = %15. Fiyat bunu aşarsa işlem iptal (tepeden alımı önler)" },
  { key: "priority_fee_sol", label: "Priority Fee (SOL)", type: "number" },
  { key: "min_wallet_score", label: "Min. Cüzdan Puanı", type: "number" },
  { key: "min_token_score", label: "Min. Token Puanı", type: "number", hint: "YALNIZCA İşlem Kapısı = 'score' modunda etkilidir (safety/balanced modda yok sayılır)" },
  { key: "max_open_positions_per_token", label: "Token Başına Maks. Pozisyon", type: "number" },
  { key: "max_follow_lag_seconds", label: "Maks. İzleme Gecikmesi (sn)", type: "number" },
  { key: "min_liquidity_sol", label: "Min. Likidite (SOL)", type: "number" },
  { key: "take_profit_pct", label: "Take-Profit (oran)", type: "number", hint: "0 = kapalı. 0.5 = +%50'de otomatik sat (paper)" },
  { key: "stop_loss_pct", label: "Stop-Loss (oran)", type: "number", hint: "0 = kapalı. 0.3 = -%30'da otomatik sat (paper)" },
  { key: "copy_prune_enabled", label: "Otomatik Eleme", type: "bool", hint: "Kopya performansı kötü cüzdanları otomatik engelle" },
  { key: "copy_max_consecutive_losses", label: "Maks. Ardışık Zarar", type: "number", hint: "Bu kadar ardışık zarar eden cüzdan elenir (0 = kapalı)" },
  { key: "copy_min_closed_trades", label: "Eleme İçin Min. İşlem", type: "number", hint: "Bir cüzdanı yargılamadan önce en az bu kadar kapanmış işlem" },
  { key: "copy_max_drawdown_sol", label: "Maks. Kopya Zararı (SOL)", type: "number", hint: "Kümülatif kopya PnL bu değerin altına düşerse cüzdan elenir" },
];

const PROFILES = [
  { name: "temkinli", label: "Temkinli", icon: Shield, desc: "Küçük miktar, yüksek eşik, düşük slippage" },
  { name: "dengeli", label: "Dengeli", icon: Scale, desc: "Önerilen varsayılan ayarlar" },
  { name: "agresif", label: "Agresif", icon: Flame, desc: "Büyük miktar, düşük eşik, yüksek slippage" },
];

export default function RiskSettings() {
  const { data, mutate } = useSWR<{ value: Risk }>("/settings/risk", fetcher);
  const [form, setForm] = useState<Risk | null>(null);
  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const toast = useToast();
  const { confirm, dialog } = useConfirm();

  useEffect(() => { if (data?.value) setForm(data.value); }, [data]);
  if (!form) return <Loading />;

  async function runTest() {
    setTesting(true); setTestResult(null);
    try {
      const r: any = await apiSend("/trading/test-run", "POST");
      setTestResult(r);
      if (r?.result?.traded) toast("success", "Test işlem AÇILDI ✓");
      else if (r?.ok) toast("info", "Test çalıştı — sonucu aşağıda gör");
      else toast("info", r?.reason || "Test sonucu aşağıda");
    } catch (e: any) { toast("error", e?.message || "Test başarısız"); }
    finally { setTesting(false); }
  }

  function set(k: string, v: any) { setForm({ ...form, [k]: v }); }

  async function save() {
    if (!form) return;
    // Canlı moda geçişte ek onay
    if ((form.mode === "live" || form.live_confirmed) && form.enabled) {
      const ok = await confirm({
        title: "Canlı işlem onayı",
        body: "GERÇEK PARA ile işlem yapılacak. Ayrı ve düşük bakiyeli bir cüzdan kullandığından emin ol. Devam edilsin mi?",
        confirmText: "Evet, canlı işlemi aç", danger: true,
      });
      if (!ok) return;
      form.live_confirmed = true;
    }
    try { await apiSend("/settings/risk", "PUT", { value: form }); await mutate(); toast("success", "Risk ayarları kaydedildi"); }
    catch (e: any) { toast("error", e?.message || "Kaydedilemedi"); }
  }

  async function applyProfile(name: string) {
    try {
      const res: any = await apiSend(`/setup/risk-profiles/${name}`, "POST");
      setForm(res.risk); await mutate();
      toast("success", `"${name}" profili uygulandı`);
    } catch (e: any) { toast("error", e?.message || "Profil uygulanamadı"); }
  }

  async function emergencyStop() {
    const ok = await confirm({ title: "Acil Durdurma", body: "Tüm yeni işlemler durdurulacak ve motor kapatılacak.", confirmText: "Durdur", danger: true });
    if (!ok) return;
    await apiSend("/trading/emergency-stop?close_positions=false", "POST");
    await mutate(); toast("info", "Acil durdurma etkinleştirildi");
  }

  return (
    <div>
      {dialog}
      <PageHeader title="Risk Ayarları" subtitle="Kopya işlem limitleri ve davranışı"
        action={<div className="flex gap-2">
          <button className="btn" disabled={testing} onClick={runTest}>🧪 {testing ? "Çalışıyor…" : "Test İşlem Çalıştır"}</button>
          <button className="btn-danger" onClick={emergencyStop}>⛔ Acil Durdurma</button>
          <button className="btn-primary" onClick={save}><Save size={15} /> Kaydet</button>
        </div>} />

      {testResult && (
        <div className="mb-4"><Callout kind={testResult?.result?.traded ? "info" : "warn"}>
          <b>Test sonucu:</b>{" "}
          {testResult.ok === false ? (
            <span>{testResult.reason}</span>
          ) : testResult.result?.traded ? (
            <span>✅ İŞLEM AÇILDI — cüzdan {String(testResult.wallet).slice(0, 4)}… → token {String(testResult.token).slice(0, 4)}… ·
              token puanı {Math.round(testResult.result.token_score)} · kapı geçti. (İşlem Geçmişi'ne bak.)</span>
          ) : (
            <span>İşlem AÇILMADI. Sebep: <b>{testResult.result?.reason
              || (testResult.result?.trade_blocked ? "motor: " + testResult.result.trade_blocked.join(", ") : "bilinmiyor")}</b>
              {" "}· token puanı {Math.round(testResult.result?.token_score ?? 0)} · kapı {testResult.result?.token_ok ? "geçti" : "geçmedi"}.</span>
          )}
        </Callout></div>
      )}

      {form.emergency_stop && <div className="mb-4"><Callout kind="warn">⛔ Acil durdurma şu an etkin. Yeni işlem yapılmaz. Tekrar açmak için "İşlem Motoru Aktif"i açıp kaydet.</Callout></div>}

      <Section title="Hazır Profiller">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {PROFILES.map((p) => {
            const Icon = p.icon;
            return (
              <button key={p.name} className="card card-hover text-left" onClick={() => applyProfile(p.name)}>
                <div className="flex items-center gap-2 font-semibold"><Icon size={18} className="brand" /> {p.label}</div>
                <div className="mt-1 text-xs muted">{p.desc}</div>
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="İşlem Kapısı (token filtresi)">
        <p className="text-xs muted mb-3">
          Takipteki bir cüzdan token aldığında işlemin AÇILMASI için tokenin hangi
          süzgeçten geçeceğini belirler. Taze pump.fun token'leri henüz adil puanlanamaz
          (likidite/holder verisi yok); asıl sinyal <b>cüzdandır</b>.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { v: "safety", label: "Güvenlik (önerilen)", desc: "Yalnızca scam vetosu (rug/honeypot/aktif mint-freeze/sahte likidite) yoksa işlem aç. En çok işlem; cüzdana güven." },
            { v: "balanced", label: "Dengeli", desc: "Güvenlik vetosu + token puanı ≥ 55. Taze token'lerin çoğu bu eşiği geçemez → az işlem." },
            { v: "score", label: "Katı (score)", desc: "Güvenlik + 'Min. Token Puanı' eşiği. En seçici; çok az işlem." },
          ].map((g) => {
            const active = (form.token_gate || "safety") === g.v;
            return (
              <button key={g.v} className={active ? "card text-left" : "card card-hover text-left"}
                style={active ? { borderColor: "#10b981", boxShadow: "0 0 0 1px #10b981" } : {}}
                onClick={() => set("token_gate", g.v)}>
                <div className="flex items-center gap-2 font-semibold">
                  {active && <span style={{ color: "#10b981" }}>✓</span>} {g.label}
                </div>
                <div className="mt-1 text-xs muted">{g.desc}</div>
              </button>
            );
          })}
        </div>
        <div className="mt-2 text-xs muted">Aktif kapı: <b>{form.token_gate || "safety"}</b> · değiştirdikten sonra <b>Kaydet</b>'e bas.</div>
      </Section>

      <div className="mt-4"><Callout kind="warn">
        <b>Slippage</b> en önemli korumandır: hedef alım yaptıktan sonra fiyat uçar ve senin tavanını aşarsa işlem
        <b> gerçekleşmez</b> — yani tepeden alıp zarar etmezsin, sadece küçük ağ ücreti kaybedersin.
      </Callout></div>

      <div className="card mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        {FIELDS.map((f) => (
          <div key={f.key}>
            <label className="text-sm font-medium">{f.label}</label>
            {f.hint && <div className="text-xs muted">{f.hint}</div>}
            {f.type === "bool" ? (
              <button className={form[f.key] ? "btn-primary mt-1" : "btn mt-1"} onClick={() => set(f.key, !form[f.key])}>
                {form[f.key] ? "Açık" : "Kapalı"}
              </button>
            ) : (
              <input className="input mt-1" type={f.type === "number" ? "number" : "text"} step="any"
                value={form[f.key] ?? ""} onChange={(e) => set(f.key, f.type === "number" ? parseFloat(e.target.value) : e.target.value)} />
            )}
          </div>
        ))}
      </div>

      <Section title="Engelleme & Seçili Kopyalama">
        <p className="text-xs muted mb-2">Virgülle ayrılmış adresler.</p>
        {[
          { key: "blocked_wallets", label: "Engellenen Cüzdanlar" },
          { key: "blocked_tokens", label: "Engellenen Tokenler" },
          { key: "only_wallets", label: "Yalnızca Bu Cüzdanları Kopyala (boşsa tümü)" },
        ].map((f) => (
          <div key={f.key} className="mb-3">
            <label className="text-sm">{f.label}</label>
            <input className="input mt-1" value={(form[f.key] || []).join(",")}
              onChange={(e) => set(f.key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
          </div>
        ))}
      </Section>
    </div>
  );
}

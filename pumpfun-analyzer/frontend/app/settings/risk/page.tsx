"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetcher, apiSend, fmtNum } from "@/lib/api";
import { PageHeader } from "@/components/Confidence";
import { Section, Callout, InfoTip } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/ConfirmDialog";
import { Loading } from "@/components/States";
import { Shield, Scale, Flame, Save, BrainCircuit, CopyCheck } from "lucide-react";

type Risk = Record<string, any>;
type Field = { key: string; label: string; type: "number" | "bool" | "text" | "select"; hint: string; options?: { value: string; label: string }[]; suffix?: string };

const MODE_OPTIONS = [
  { value: "paper", label: "Paper" },
  { value: "alerts_only", label: "Sadece Bildirim" },
  { value: "live", label: "Canlı" },
];
const GATE_OPTIONS = [
  { value: "safety", label: "Sadece Güvenlik" },
  { value: "balanced", label: "Dengeli" },
  { value: "score", label: "Skor Eşiği" },
];
const AI_PROFILE_OPTIONS = [
  { value: "safe", label: "Güvenli" },
  { value: "balanced", label: "Dengeli" },
  { value: "opportunistic", label: "Fırsatçı" },
];

const COMMON: Field[] = [
  { key: "mode", label: "İşlem modu", type: "select", options: MODE_OPTIONS, hint: "Paper gerçek para kullanmaz. Sadece Bildirim işlem açmaz. Canlı gerçek PumpPortal emri gönderir." },
  { key: "enabled", label: "İşlem motoru", type: "bool", hint: "Kapalıysa AI veya Copy fark etmez, hiçbir yeni işlem açılmaz." },
  { key: "paper_trade_sol", label: "Paper işlem başına SOL", type: "number", suffix: "SOL", hint: "Paper modda her denemede kullanılacak sanal SOL miktarı. Sonuçları adil karşılaştırmak için sabit kalmalı." },
  { key: "fixed_sol_amount", label: "Canlı işlem başına SOL", type: "number", suffix: "SOL", hint: "Canlı modda tek alımda harcanacak gerçek SOL miktarı. Küçük bakiye testinde 0.01 gibi düşük tut." },
  { key: "max_position_sol", label: "Maksimum pozisyon", type: "number", suffix: "SOL", hint: "Tek token için ayrılabilecek maksimum SOL. İşlem başına miktar bunu aşamaz." },
  { key: "max_daily_spend_sol", label: "Günlük maksimum harcama", type: "number", suffix: "SOL", hint: "Botun bir günde yeni alımlara harcayabileceği toplam limit. Bu dolunca yeni alım açmaz." },
  { key: "max_daily_loss_sol", label: "Günlük maksimum zarar", type: "number", suffix: "SOL", hint: "Gerçekleşen zarar bu limite ulaşınca yeni işlem durur. Canlı testte düşük tutulmalı." },
  { key: "max_slippage", label: "Maksimum slippage", type: "number", hint: "0.15 = %15. Fiyat sen girene kadar bundan fazla bozulursa işlem iptal olur; tepeden alımı azaltır." },
  { key: "priority_fee_sol", label: "Priority fee", type: "number", suffix: "SOL", hint: "Solana işlem öncelik ücreti. Çok düşük olursa emir geç kalabilir, çok yüksek olursa küçük işlemlerde kârı yer." },
  { key: "max_open_positions_per_token", label: "Token başına açık pozisyon", type: "number", hint: "Aynı tokena kaç ayrı açık işlem izin verileceği. Meme tokenlarda genelde 1 daha güvenlidir." },
];

const AI_AUTOPILOT: Field[] = [
  { key: "ai_auto_manage", label: "AI otomatik yönetim", type: "bool", hint: "Açıksa token yaşı, skor kapısı, fiyat şartı gibi detayları AI risk profiline göre sistem belirler. Günlük kullanımda açık kalmalı." },
  { key: "ai_risk_profile", label: "AI risk iştahı", type: "select", options: AI_PROFILE_OPTIONS, hint: "Güvenli daha az işlem, dengeli önerilen varsayılan, fırsatçı daha çok paper denemesi üretir." },
  { key: "ai_live_enabled", label: "AI canlı kilidi", type: "bool", hint: "Kapalıysa AI Trade gerçek para ile alım yapmaz. Önce paper sonuçlarını görmeden açma." },
  { key: "ai_show_advanced", label: "Gelişmiş AI ayarlarını göster", type: "bool", hint: "Kapalıyken token yaşı/skor gibi ham değerler gizlenir. AI otomatik yönetim açıksa bu alanlara normalde gerek yoktur." },
  { key: "ai_fresh_universe_enabled", label: "AI sadece taze launch evreni", type: "bool", hint: "Açıksa AI eski/az hareketli tokenları fırsat evreni dışında bırakır. Ana hedef yeni pump potansiyeli olan tokenları izlemektir." },
];

const AI_ENTRY: Field[] = [
  { key: "ai_min_token_score", label: "Manuel minimum token puanı", type: "number", hint: "Sadece AI otomatik yönetim kapalıysa kullanılır. AI Trade’in alım için istediği minimum token skoru." },
  { key: "ai_token_gate", label: "Manuel token kapısı", type: "select", options: GATE_OPTIONS, hint: "Sadece AI otomatik yönetim kapalıysa kullanılır. score en seçici moddur; safety yalnızca güvenlik vetosuna bakar." },
  { key: "ai_min_liquidity_sol", label: "Manuel minimum likidite", type: "number", suffix: "SOL", hint: "Sadece gelişmiş override için. Ölçülebiliyorsa minimum likidite." },
  { key: "ai_min_token_age_seconds", label: "Manuel minimum token yaşı", type: "number", suffix: "sn", hint: "Sadece AI otomatik yönetim kapalıysa kullanılır. İlk saniyelerdeki sniper savaşını atlamak için minimum yaş." },
  { key: "ai_max_token_age_minutes", label: "Manuel maksimum token yaşı", type: "number", suffix: "dk", hint: "AI taze launch evreni açıksa bu sınırdan eski tokenlar AI tarafından alınmaz; otomatik yönetimde profil kendi değerini seçer." },
  { key: "ai_require_known_token_age", label: "Manuel yaş bilinmiyorsa blokla", type: "bool", hint: "Sadece gelişmiş override için. Yaş okunamıyorsa AI işlem açmaz." },
  { key: "ai_require_price", label: "Manuel güvenilir fiyat şartı", type: "bool", hint: "Sadece gelişmiş override için. Giriş fiyatı güvenilir değilse AI işlem açmaz." },
];

const EXIT: Field[] = [
  { key: "take_profit_pct", label: "Take-profit", type: "number", hint: "0.50 = +%50 kârda pozisyonu kapat. 0 kapalı demektir." },
  { key: "stop_loss_pct", label: "Stop-loss", type: "number", hint: "0.25 = -%25 zararda pozisyonu kapat. Rug riskine karşı ana frendir." },
  { key: "trail_activate_pct", label: "Trailing aktivasyon", type: "number", hint: "0.15 = pozisyon +%15 kâra gelince takip eden stop devreye girer." },
  { key: "trailing_stop_pct", label: "Trailing stop", type: "number", hint: "0.12 = zirveden %12 düşerse çık. Pump yakalarken dönüşte kârı korur." },
  { key: "max_hold_minutes", label: "Maksimum tutma süresi", type: "number", suffix: "dk", hint: "Süre dolunca pozisyon kapanır. Taze tokenlar sönmeden çıkmak için kullanılır." },
];

const COPY_ENTRY: Field[] = [
  { key: "min_wallet_score", label: "Minimum cüzdan puanı", type: "number", hint: "Copy Trade’de takip cüzdanının geçmesi gereken minimum skor." },
  { key: "token_gate", label: "Copy token kapısı", type: "select", options: GATE_OPTIONS, hint: "Copy alımında tokenın hangi kalite/güvenlik kapısından geçeceğini belirler." },
  { key: "min_token_score", label: "Minimum token puanı", type: "number", hint: "Sadece token kapısı score ise çalışır. Taze tokenlarda çok yüksek eşik az işlem üretir." },
  { key: "max_follow_lag_seconds", label: "Maksimum takip gecikmesi", type: "number", suffix: "sn", hint: "Lider aldıktan sonra sinyal bu süreyi aşarsa alım yapılmaz. Geç girişte tepeden alma riskini azaltır." },
  { key: "min_confluence", label: "Minimum mutabakat", type: "number", hint: "1 kapalı demektir. 2 yaparsan aynı tokenı kısa sürede 2 takip cüzdanı almadan işlem açmaz." },
  { key: "confluence_window_minutes", label: "Mutabakat penceresi", type: "number", suffix: "dk", hint: "Mutabakat sayımı için alımların kaç dakika içinde olması gerektiği." },
  { key: "proportional", label: "Orantılı kopyalama", type: "bool", hint: "Açıksa canlıda liderin işlem miktarına oranlı alım denenir. Sabit 0.01 SOL testinde kapalı kalması daha temizdir." },
];

const COPY_QUALITY: Field[] = [
  { key: "block_sniper_wallets_live", label: "Canlıda sniper/scalper engelle", type: "bool", hint: "Çok hızlı al-sat yapan cüzdanların canlı alımları engellenir." },
  { key: "live_min_median_hold_seconds", label: "Min. medyan tutma", type: "number", suffix: "sn", hint: "Medyan tutma süresi bunun altındaki cüzdan canlıda bloklanır." },
  { key: "live_max_short_hold_ratio", label: "Maks. kısa satış oranı", type: "number", hint: "0.45 = işlemlerin %45’ten fazlası kısa sürede kapanıyorsa blok." },
  { key: "live_min_copyability_score", label: "Min. copyability score", type: "number", hint: "10sn gecikmeli copy simülasyonundan gelen kalite puanı." },
  { key: "live_min_copy_sample", label: "Min. copy örneklem", type: "number", hint: "Cüzdan canlıya alınmadan önce kaç geçmiş copy simülasyonu istenir." },
  { key: "live_require_copy_sample", label: "Copy örneklemi şart", type: "bool", hint: "Açıksa yeterli gecikmeli copy verisi olmayan cüzdan canlı alım açamaz." },
  { key: "live_require_positive_copy_pnl_10s", label: "10sn copy PnL pozitif şart", type: "bool", hint: "Açıksa 10 saniye gecikmeli kopya simülasyonu kârlı olmayan cüzdan canlıda bloklanır." },
  { key: "live_max_entry_jump_10s", label: "Maks. 10sn entry jump", type: "number", hint: "0.15 = liderden 10 sn sonra fiyat %15’ten fazla zıplamışsa canlıda blok." },
];

const TOKEN_FRESH: Field[] = [
  { key: "live_fresh_token_only", label: "Sadece taze token", type: "bool", hint: "Açıksa eski tokenlar canlıda alınmaz. Pump potansiyeli olan yeni tokenlara odaklanır." },
  { key: "live_min_token_age_seconds", label: "Min. token yaşı", type: "number", suffix: "sn", hint: "İlk saniyedeki sniper savaşını atlamak için minimum yaş." },
  { key: "live_max_token_age_minutes", label: "Maks. token yaşı", type: "number", suffix: "dk", hint: "Bu süreden eski tokenlar alınmaz." },
  { key: "live_require_known_token_age", label: "Yaş bilinmiyorsa blokla", type: "bool", hint: "Yaş verisi yoksa canlı alımı durdurur. Güvenli ama daha az işlem üretir." },
];

const COPY_EXIT: Field[] = [
  { key: "pure_mirror_mode", label: "Saf kopya modu", type: "bool", hint: "Açıksa Copy Trade’de TP/SL/trailing devre dışı kalır; sadece lider satışı ve leader-watch çıkış sağlar." },
  ...EXIT,
];

const PRUNE: Field[] = [
  { key: "copy_prune_enabled", label: "Otomatik cüzdan eleme", type: "bool", hint: "Bize zarar ettiren cüzdanları copy performansına göre otomatik düşürür." },
  { key: "copy_max_consecutive_losses", label: "Maks. ardışık zarar", type: "number", hint: "Bu kadar üst üste zarar yazan cüzdan geçici/kalıcı olarak elenir." },
  { key: "copy_min_closed_trades", label: "Eleme için min. işlem", type: "number", hint: "Bir cüzdanı yargılamadan önce gereken minimum kapanmış işlem sayısı." },
  { key: "copy_min_pnl_sol", label: "Min. copy PnL", type: "number", suffix: "SOL", hint: "Yeterli işlemden sonra kopya PnL bu değerin altındaysa cüzdan elenir." },
];

const PROFILES = [
  { name: "temkinli", label: "Temkinli", icon: Shield, desc: "Küçük miktar, yüksek eşik, düşük slippage" },
  { name: "dengeli", label: "Dengeli", icon: Scale, desc: "Önerilen varsayılan ayarlar" },
  { name: "agresif", label: "Agresif", icon: Flame, desc: "Büyük miktar, düşük eşik, yüksek slippage" },
];

function FieldInput({ f, form, set }: { f: Field; form: Risk; set: (k: string, v: any) => void }) {
  const val = form[f.key];
  return (
    <div className="setting-field">
      <label className="flex items-center gap-1 text-sm font-semibold">
        {f.label}<InfoTip title={f.label}>{f.hint}</InfoTip>
      </label>
      <div className="mt-1 text-xs muted leading-relaxed">{f.hint}</div>
      {f.type === "bool" ? (
        <button className={val ? "toggle-btn on" : "toggle-btn"} onClick={() => set(f.key, !val)}>{val ? "Açık" : "Kapalı"}</button>
      ) : f.type === "select" ? (
        <select className="input mt-2" value={val ?? ""} onChange={(e) => set(f.key, e.target.value)}>
          {(f.options || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : (
        <div className="relative mt-2">
          <input className="input pr-12" type={f.type === "number" ? "number" : "text"} step="any" value={val ?? ""}
            onChange={(e) => set(f.key, f.type === "number" ? (e.target.value === "" ? "" : parseFloat(e.target.value)) : e.target.value)} />
          {f.suffix && <span className="absolute right-3 top-2.5 text-xs muted">{f.suffix}</span>}
        </div>
      )}
    </div>
  );
}

function FieldSection({ title, desc, fields, form, set }: { title: string; desc: string; fields: Field[]; form: Risk; set: (k: string, v: any) => void }) {
  return (
    <Section title={title}>
      <p className="mb-4 text-sm muted">{desc}</p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {fields.map((f) => <FieldInput key={f.key} f={f} form={form} set={set} />)}
      </div>
    </Section>
  );
}

export default function RiskSettings() {
  const { data, mutate } = useSWR<{ value: Risk }>("/settings/risk", fetcher);
  const [form, setForm] = useState<Risk | null>(null);
  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const toast = useToast();
  const { confirm, dialog } = useConfirm();

  useEffect(() => { if (data?.value) setForm(data.value); }, [data]);
  const strategy = ((form?.strategy_mode || "copy") as "ai" | "copy");
  const isAi = strategy === "ai";
  if (!form) return <Loading />;

  function set(k: string, v: any) { setForm({ ...form, [k]: v }); }

  async function runTest() {
    setTesting(true); setTestResult(null);
    try {
      const r: any = await apiSend("/trading/test-run", "POST");
      setTestResult(r);
      if (r?.result?.traded) toast("success", "Test işlem açıldı");
      else toast("info", r?.reason || r?.result?.reason || "Test tamamlandı");
    } catch (e: any) { toast("error", e?.message || "Test başarısız"); }
    finally { setTesting(false); }
  }

  async function save() {
    const next = { ...form };
    if (next.enabled && next.emergency_stop) next.emergency_stop = false;
    if ((next.mode === "live" || next.live_confirmed) && next.enabled) {
      const ok = await confirm({
        title: "Canlı işlem onayı",
        body: "GERÇEK PARA ile işlem yapılacak. Ayrı ve düşük bakiyeli bir cüzdan kullandığından emin ol. Devam edilsin mi?",
        confirmText: "Evet, canlı işlemi aç", danger: true,
      });
      if (!ok) return;
      next.live_confirmed = true;
    }
    try {
      await apiSend("/settings/risk", "PUT", { value: next });
      setForm(next); await mutate(); toast("success", "Ayarlar kaydedildi");
    } catch (e: any) { toast("error", e?.message || "Kaydedilemedi"); }
  }

  async function applyProfile(name: string) {
    try {
      const res: any = await apiSend(`/setup/risk-profiles/${name}`, "POST");
      const keepStrategy = { ...res.risk, strategy_mode: strategy };
      setForm(keepStrategy); await mutate();
      toast("success", `${name} profili uygulandı`);
    } catch (e: any) { toast("error", e?.message || "Profil uygulanamadı"); }
  }

  async function emergencyStop() {
    const ok = await confirm({ title: "Acil Durdurma", body: "Tüm yeni işlemler durdurulacak ve motor kapatılacak.", confirmText: "Durdur", danger: true });
    if (!ok) return;
    await apiSend("/trading/emergency-stop?close_positions=false", "POST");
    await mutate(); toast("info", "Acil durdurma etkinleştirildi");
  }

  return (
    <div className="space-y-5">
      {dialog}
      <PageHeader title={isAi ? "AI Risk Ayarları" : "Copy Risk Ayarları"} subtitle="Sadece aktif moda ait ayarlar gösterilir. Her soru işareti ayarın ne işe yaradığını anlatır."
        action={<div className="flex flex-wrap gap-2">
          <button className="btn" disabled={testing} onClick={runTest}>🧪 {testing ? "Çalışıyor…" : "Test"}</button>
          <button className="btn-danger" onClick={emergencyStop}>⛔ Acil Durdurma</button>
          <button className="btn-primary" onClick={save}><Save size={15} /> Kaydet</button>
        </div>} />

      {form.emergency_stop && <Callout kind="warn">⛔ Acil durdurma etkin. Yeni işlem açılmaz. Motoru tekrar açıp kaydedince bu kilit temizlenir.</Callout>}
      {testResult && <Callout kind={testResult?.result?.traded ? "info" : "warn"}>Test sonucu: {testResult?.result?.traded ? "işlem açıldı" : (testResult?.reason || testResult?.result?.reason || testResult?.result?.trade_blocked?.join(", ") || "işlem açılmadı")}</Callout>}

      <Section title="Çalışma modu">
        <div className="grid gap-3 md:grid-cols-2">
          {[
            { v: "ai", title: "AI TRADE", icon: BrainCircuit, desc: "Cüzdanları ana karar yapmaz. Taze token fırsatlarını token kalitesiyle ölçer." },
            { v: "copy", title: "COPY TRADE", icon: CopyCheck, desc: "Takip edilen cüzdanları copyability ve güvenlik filtreleriyle kopyalar." },
          ].map((m) => {
            const Icon = m.icon;
            const active = strategy === m.v;
            return (
              <button key={m.v} className={active ? "mode-select-tile active" : "mode-select-tile"} onClick={() => set("strategy_mode", m.v)}>
                <Icon size={22} />
                <div className="text-left"><b>{m.title}</b><p>{m.desc}</p></div>
                {active && <span className="badge">Aktif</span>}
              </button>
            );
          })}
        </div>
        <div className="mt-3 text-xs muted">Modu değiştirip kaydedince diğer motor arka planda durur. AI aktifken copy cüzdan arama/izleme çalışmaz; Copy aktifken AI token motoru işlem üretmez.</div>
      </Section>

      <Section title="Hazır profiller">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {PROFILES.map((p) => {
            const Icon = p.icon;
            return <button key={p.name} className="card card-hover text-left" onClick={() => applyProfile(p.name)}><div className="flex items-center gap-2 font-semibold"><Icon size={18} className="brand" /> {p.label}</div><div className="mt-1 text-xs muted">{p.desc}</div></button>;
          })}
        </div>
      </Section>

      <FieldSection title="Bütçe ve işlem motoru" desc="Bu bölüm iki modda da ortaktır. Paper ve canlı işlemin büyüklüğünü, günlük limiti ve motor durumunu belirler." fields={COMMON} form={form} set={set} />

      {isAi ? (
        <>
          <FieldSection title="AI otomatik yönetim" desc="AI Trade’de normalde token yaşı, skor kapısı ve fiyat şartı gibi ham kriterleri sen tek tek seçmezsin. Risk iştahını seçersin; sistem etkin eşikleri kendisi uygular." fields={AI_AUTOPILOT} form={form} set={set} />
          {(form.ai_show_advanced || form.ai_auto_manage === false) && (
            <FieldSection title="Gelişmiş manuel AI override" desc="Bu alanlar yalnızca otomatik yönetimi kapatırsan karar motorunu doğrudan etkiler. Emin değilsen otomatik yönetimi açık bırak." fields={AI_ENTRY} form={form} set={set} />
          )}
          <FieldSection title="AI çıkış planı" desc="AI pozisyonlarında lider cüzdan yoktur. Çıkış TP, SL, trailing stop ve maksimum süreyle yönetilir." fields={EXIT} form={form} set={set} />
        </>
      ) : (
        <>
          <FieldSection title="Copy giriş kuralları" desc="Hangi cüzdan sinyalinin işleme dönüşeceğini belirler. Cüzdan kalitesi, gecikme, token kapısı ve mutabakat burada yönetilir." fields={COPY_ENTRY} form={form} set={set} />
          <FieldSection title="Copy canlı kalite filtresi" desc="Sniper/scalper ve gecikmede zarar ettiren cüzdanları canlıda engeller. Paper daha geniş ölçebilir; canlı daha katı olmalı." fields={COPY_QUALITY} form={form} set={set} />
          <FieldSection title="Taze token filtresi" desc="Eski tokenlarda marj daralır. Bu filtre copy sistemini taze pump potansiyelli tokenlara yaklaştırır." fields={TOKEN_FRESH} form={form} set={set} />
          <FieldSection title="Copy çıkış ve eleme" desc="Saf kopya, otomatik çıkış ve zarar ettiren cüzdanların elenmesi burada yönetilir." fields={[...COPY_EXIT, ...PRUNE]} form={form} set={set} />
        </>
      )}

      <Section title="Engelleme listeleri">
        <p className="mb-3 text-sm muted">Bu listeler iki modda da çalışır. Virgülle ayrılmış adres/mint yaz.</p>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            { key: "blocked_wallets", label: "Engellenen cüzdanlar", hint: "Copy Trade’de bu cüzdanlardan gelen sinyaller işlenmez. AI Trade’de ana karar cüzdan olmadığı için etkisi sınırlıdır." },
            { key: "blocked_tokens", label: "Engellenen tokenler", hint: "Bu tokenlar hangi mod açık olursa olsun alınmaz." },
            { key: "only_wallets", label: "Sadece bu cüzdanları kopyala", hint: "Copy Trade için özel beyaz liste. Boşsa tüm takip edilen cüzdanlar değerlendirilir." },
          ].map((f) => (
            <div key={f.key} className="setting-field">
              <label className="flex items-center gap-1 text-sm font-semibold">{f.label}<InfoTip title={f.label}>{f.hint}</InfoTip></label>
              <textarea className="input mt-2 min-h-[90px]" value={(form[f.key] || []).join(",")}
                onChange={(e) => set(f.key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

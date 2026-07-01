# TESLİM NOTU — BUILD 74 → 76 (Claude, mimari/karar merkezi)

Build 73 (ChatGPT ile geliştirilen sürüm) esas alınarak, **mevcut çalışan yapı
bozulmadan** üst seviyeye taşıma çalışması. `.env` / private key / API key
dosyalarına dokunulmadı; hiçbiri commit edilmedi. Her adımda backend testleri +
frontend derlemesi doğrulandı.

Doğrulama durumu (son): **172 backend testi yeşil**, `tsc --noEmit` temiz,
`next build` başarılı.

---

## 1) Yapılan değişiklikler

### BUILD 74 — Stabilizasyon (17 hata → 0)
Build 73 içe aktarıldığında **kendi test paketinde 17 hata** veriyordu. Kök
nedenler giderildi:

- **Copyability skorlama uyumu:** copyability verisi YOKKEN (taze cüzdan / az
  örneklem / fiyat proxy'si eksik) %25'lik nötr(50) yük skoru düşürüyordu. Artık
  copyability ağırlığı düşürülüp kalan bileşenler normalize ediliyor (fail-open
  takip). `copyability_metrics` dolu ama `sample=0` ise de "veri yok" sayılır.
- `copyability_require_min_sample` varsayılanı **False** (simüle edilemeyen
  cüzdanı otomatik reddetmek aday havuzunu çökertiyordu; sert kapı yalnız veri
  VARKEN uygulanır).
- `copyability_min_sample` **12 → 6** (senin orijinal spec'inle hizalı).
- `max_days_since_last_trade` **3 → 7** (pump.fun için makul "hâlâ aktif" penceresi).
- **Copyability simülasyonu düzeltmesi:** follower girişi artık liderin KENDİ
  satış tikinden ÖNCEYE zorlanıyor (`_first_price_at_or_after(before=...)`). Ara
  fiyat verisi olmayan gerçek trade artık uydurma "chase/zarar" üretmiyor.
- Leaderboard `limit` doğrudan çağrıda Query default'una karşı int'e sabitlendi.
- Satır sonları LF'e normalize edildi (build 73 .rar'ı karışık CRLF getirmişti;
  ayrı bir commit'te temizlendi ki mantık diff'i okunur kalsın).

### BUILD 75 — Veri sağlayıcı sağlık takibi + sağlık paneli
"Helius zorunlu değil / çok-sağlayıcılı / kötü veriyle işlem yapma / degraded
mode / sağlayıcı sağlık paneli" spec maddelerinin **gözlem omurgası**. Additive,
düşük riskli — akış davranışı değişmez, sadece izlenir.

- `services/provider_health.py`: in-process, thread-safe kayıt. Her market/chain
  çağrısının ok/fail, gecikme (EMA), üst üste hata, son hatası tutulur; son 20
  çağrıya göre **ok / degraded / down / unknown** sınıflanır. `overall_status()`
  ve `market_data_reliable()` fail-safe sinyalleri üretir.
- `adapters/health_tracking.py`: Chain/Market sağlayıcılar için decorator
  sarmalayıcı — davranış aynen geçer, sadece kaydedilir.
- `/api/health` genişletildi (`data_status`, `market_data_reliable`, `providers`);
  yeni `/api/providers` endpoint'i döküm verir.
- Frontend **Sistem Sağlığı** sayfasına "Veri Sağlayıcı Sağlığı" kartı: durum
  rozetleri, başarı oranı, gecikme, son ok zamanı, üst üste hata, açıklayıcı
  InfoTip ve güvenilmez-veri uyarı banner'ı.

### BUILD 76 — Veri-yok/hata ayrımı + alım fail-safe kapısı
- **Kritik doğruluk düzeltmesi:** DexScreener/Birdeye taze token için "çift yok"
  derken de gerçek ağ hatasında da `ok=False` dönüyordu. Ayrım yapılmayınca
  NORMAL fresh-token copy-trade sağlayıcıyı yanlışlıkla "down" gösterirdi.
  `TokenMarketData.error` alanı eklendi: **yalnızca gerçek taşıma hatasında**
  dolar. `ok=False + error=None` = sağlayıcı sağlıklı, sadece bu mint'in verisi yok.
- **Fail-safe kapısı:** canlı VEYA AI **yeni alım**, tüm piyasa sağlayıcılar
  "down" iken engellenir. Satış/çıkış (mirror_sell) etkilenmez — her zaman
  serbest. Kayıt yoksa (unknown) engelleme yok; mevcut per-trade fiyat
  kontrolleri korumaya devam eder.

---

## 2) Öneriler — EKLENECEKLER (öncelik sırasıyla)

1. **HelpTooltip (`?`) tam kapsama.** `InfoTip` bileşeni var; kritik ayarların
   (risk, live, api) tümüne henüz uygulanmadı. Kısa, düşük riskli UX işi. (Yüksek değer)
2. **AI kararı açıklanabilirliği ("neden aldı / neden almadı").** `live_flow`
   zaten her blok için audit log yazıyor; bunu `/logs`'ta yapılandırılmış bir
   "DecisionCard" (sinyal → geçen/kalan kapılar → sonuç) olarak göstermek büyük
   güven kazandırır. (Yüksek değer)
3. **Emergency stop'u UI'a bağla.** Ayar (`emergency_stop`) ve motor kontrolü
   zaten var; ana ekrana tek-tıkla "TÜM ALIMLARI DURDUR" düğmesi + onay dialog'u
   (`ConfirmDialog` mevcut). (Yüksek değer, düşük risk)
4. **Ek market sağlayıcı adapteri (Moralis veya Jupiter price).** Artık sağlık
   omurgası hazır; ikinci bir market kaynağı DexScreener down olduğunda otomatik
   yedek olur (gerçek çok-sağlayıcılı dayanıklılık). (Orta değer)
5. **Küme/ilişki filtresi görünürlüğü.** `wallet_relationships` + `insider`/
   `rugger` sınıflandırıcıları backend'de var; leaderboard'da "küme riski"
   rozeti olarak yüzeye çıkarmak copyability kalitesini artırır. (Orta değer)
6. **PWA/mobil manifest.** Telefon erişimi (Tailscale + same-origin proxy) çalışıyor;
   `manifest.json` + service worker eklenerek "ana ekrana ekle" deneyimi. (Düşük öncelik)

## 3) Öneriler — ÇIKARILACAK / SADELEŞTİRİLECEK

- **Satır sonu karmaşası:** repo genelinde hâlâ karışık CRLF/LF var (build 73
  .rar mirası). `.gitattributes` (`* text=auto eol=lf`) ile tek seferlik
  normalize edilmesini öneririm; ileride diff gürültüsünü tamamen bitirir.
- **Kullanılmayan/örtüşen sağlayıcılar:** `birdeye` adapteri anahtar yoksa sessiz
  `ok=False` dönüyor. API anahtarı yoksa panelde "yapılandırılmadı" olarak net
  gösterilmeli ya da varsayılan sağlayıcı listesinden çıkarılmalı (kafa karışıklığı).
- **Çok sayıda benzer sayfa** (`/paper`, `/live`, `/positions`, `/history`): tek
  bir "Portföy" sekmesi altında birleştirmek gezinmeyi sadeleştirir (mevcut
  `OverviewDashboard` bunun temeli).

## 4) Önerdiğim bir sonraki adım
Sıra: **(3) Emergency stop UI → (1) HelpTooltip kapsama → (2) AI karar kartları.**
Üçü de düşük riskli, çalışan copy-trade akışına dokunmaz ve panelin "profesyonel
terminal" hissini en hızlı yükseltir. Onayınla bunlardan başlarım.

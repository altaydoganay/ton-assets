# SATIŞA HAZIRLIK — Final Özellik Listesi ve Yol Haritası

Hedef: proje doğru çalıştığı kanıtlanırsa SATIŞA açılacak. Bu doküman "kod işini
bitirme" aşamasında eklenmesi gereken finalleri, satış modeline göre önceliklerle
listeler.

---

## 0) Acı gerçek: ürünü satan şey KOD değil, KANIT
Trading ürünü track-record ile satılır. 30+ gün doğrulanabilir paper+canlı
performans (PF, isabet, drawdown) olmadan hiçbir özellik satış getirmez.
**En değerli "final" = sistemi 30 gün kesintisiz çalıştırıp karneyi doldurmak.**
Kod finalleri bu kanıtı ÜRETMEYİ ve GÖSTERMEYİ kolaylaştırmalı.

---

## 1) OLMAZSA OLMAZ finaller (satış öncesi blocker)

| # | Özellik | Neden blocker | Efor |
|---|---------|---------------|------|
| S1 | **Kimlik doğrulama** — panel girişi (parola) + API token. Şu an panel/API TAMAMEN AÇIK: URL'e ulaşan herkes emergency stop dahil her şeyi yapabilir, canlı cüzdanı boşaltabilir. | Güvenlik; satılan üründe kabul edilemez | M |
| S2 | **Track-record sayfası + CSV dışa aktarım** — dönemsel PnL, profit factor, drawdown, işlem listesi; alıcıya gösterilecek KANIT ekranı | Satışın özü | S-M |
| S3 | **Kurulum sihirbazı** — RPC/WS endpoint'leri ve anahtarlar .env yerine panelden girilip DB'ye yazılsın (bu oturumda .env satır-birleşme hatası bile yaşadık; müşteri bunu hiç yapamaz). İlk açılışta adım adım kurulum. | Destek yükünü %80 düşürür | M |
| S4 | **Sağlık watchdog + Telegram alarmı** — listener öldü / kota bitti / motor durdu → kullanıcıya bildirim. Müşteri "bot neden durdu"yu kendisi görmeli. | Ürün güveni | S |
| S5 | **Risk onayı & yasal metin** — ilk kullanımda zorunlu "finansal tavsiye değildir / sermaye kaybı riski" onayı; canlıya geçişte ikinci onay (var, güçlendir). ToS/gizlilik taslağı. | Hukuki koruma | S |
| S6 | **İngilizce dil desteği** — pazar global; TR-only pazarı ~%95 küçültür. i18n altyapısı + EN çeviri. | Pazar boyutu | M-L |

## 2) SATIŞ MODELİ KARARI (yapıyı belirler — önce buna karar ver)

**A. Self-host lisans** (önerilen başlangıç)
- Müşteri kendi sunucusunda çalıştırır (mevcut mimari birebir uyar).
- Gerekenler: lisans anahtarı doğrulama (S7), tek-komut kurulum, güncelleme
  talimatı. En hızlı satışa çıkış (~1-2 hafta ek iş).
- Artı: anahtar/cüzdan sorumluluğu müşteride (hukuki olarak en temiz).

**B. Telegram-bot / işlem-başına ücret** (bu nişte kanıtlanmış model: Trojan,
BonkBot vb. hacimden %0.5-1 alır)
- Gerekenler: TG-bot arayüzü, fee-router, çoklu kullanıcı cüzdan yönetimi.
- En yüksek gelir potansiyeli ama EMANET (custody) riski ve ciddi ek geliştirme (L).

**C. SaaS (hosted, abonelik)**
- Gerekenler: multi-tenancy (kullanıcı başına veri/cüzdan izolasyonu), Stripe,
  kullanıcı yönetimi, bulut altyapı, KVKK/GDPR. En büyük iş (3-6+ hafta) ve en
  büyük hukuki yüzey. İlk sürüm için ÖNERİLMEZ; A kanıt ürettikten sonra düşün.

| # | Özellik | Model | Efor |
|---|---------|-------|------|
| S7 | Lisans anahtarı mekanizması (offline imzalı anahtar + süre) | A | S-M |
| S8 | Fee-router + TG arayüz | B | L |
| S9 | Multi-tenancy + billing | C | XL |

## 3) GÜÇLÜ ARTILAR (satışı kolaylaştırır, blocker değil)

| # | Özellik | Değer |
|---|---------|-------|
| S10 | **Demo modu** — örnek veriyle dolu salt-okunur panel (satış görüşmesinde gösterilir) | Yüksek |
| S11 | CI (GitHub Actions: pytest + tsc + build) — alıcı due-diligence'ında ciddiyet kanıtı | Orta |
| S12 | Yedekleme/geri yükleme (tek komut DB dump + ayar dışa aktarım) | Orta |
| S13 | Landing page + kısa video + fiyatlandırma sayfası | Yüksek (pazarlama) |
| S14 | Sentry/hata raporlama (müşteri ortamındaki hatayı sen gör) | Orta |
| S15 | PWA/mobil cila (mevcut Tailscale akışının üstüne) | Düşük |

## 4) SATIŞ ÖNCESİ TEMİZLİK (due diligence)
- PumpPortal data-path'i tamamen kaldır ya da "legacy" olarak izole et (yarım kalan yol izlenimi vermesin).
- README'yi ürün diliyle yeniden yaz (kurulum, mimari, SSS).
- Bağımlılık lisans taraması (hepsi permissive OSS — sorun beklenmiyor, belgelensin).
- `.env.example`'daki gerçek anahtar kalıntılarını tara (bu repoda temiz; müşteri paketinde otomatik kontrol).

---

## ÖNERİLEN SIRA (minimum satılabilir ürün)
1. **S1 Auth** → 2. **S3 Kurulum sihirbazı** → 3. **S2 Track-record+export** →
4. **S4 Watchdog alarmı** → 5. **S5 Yasal onay** → (paralelde 30 gün kanıt koşusu)
→ 6. **S7 Lisans** → 7. **S6 EN dili** → satışa aç. S10-S13 pazarlamayla birlikte.

Tahmini toplam: ~2-3 hafta yoğun iş (S6 hariç ~1.5 hafta).

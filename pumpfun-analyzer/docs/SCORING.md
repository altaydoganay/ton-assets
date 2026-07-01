# Puanlama ve Copyability

Sistem artık cüzdanları yalnızca liderin kendi kazancına göre değil, **0.01 SOL ile gecikmeli kopyalanınca sonuç bırakıyor mu?** sorusuna göre sıralar.

Kaynak dosyalar:

- `backend/app/core/analysis/pnl.py`
- `backend/app/core/analysis/copyability.py`
- `backend/app/core/scoring/wallet_scoring.py`
- `backend/app/services/pipeline.py`
- `backend/app/services/culling.py`

## FIFO PnL

`pnl.py` lider cüzdanın kendi performansını FIFO ile hesaplar.

- Alış lot açar: `sol_amount + fee_sol`
- Satış en eski lotlardan kapatır.
- Açık pozisyonlar kazanılmış sayılmaz.
- Kapalı pozisyonlardan win rate, realized PnL, profit factor, drawdown, hold time ve tek işlem kâr yoğunluğu hesaplanır.

## Copyability Simülasyonu

`copyability.py` mevcut `Swap` kayıtlarını kullanır. Veritabanı modeli değiştirilmez; sonuçlar `wallet.metrics` JSON içine yazılır.

Varsayılanlar:

- Copy amount: `0.01 SOL`
- Delay listesi: `5s`, `10s`, `30s`
- Ana karar: `10s`
- Slippage: risk ayarındaki `max_slippage`
- Priority fee: risk ayarındaki `priority_fee_sol`

Her kapalı lider pozisyonu için:

1. Lider buy zamanı ve buy fiyatı bulunur.
2. Lider sell zamanı ve sell fiyatı bulunur.
3. Follower buy zamanı: `leader_buy_time + delay`
4. O zamandan sonraki ilk güvenilir fiyat alınır.
5. Follower `0.01 SOL` ile almış gibi hesaplanır.
6. Lider sattığında follower da satar.
7. Alış/satışta slippage ve priority fee düşülür.
8. Fiyat yoksa trade kârlı sayılmaz; `not_simulatable_count` ve coverage içine girer.

Üretilen metrikler:

- `copy_pnl_5s_sol`
- `copy_pnl_10s_sol`
- `copy_pnl_30s_sol`
- `copy_win_rate_5s`
- `copy_win_rate_10s`
- `copy_win_rate_30s`
- `copy_profit_factor_10s`
- `copy_sample_size`
- `copy_coverage_ratio`
- `not_simulatable_count`
- `avg_entry_jump_5s`
- `avg_entry_jump_10s`
- `avg_entry_jump_30s`
- `median_entry_jump_10s`
- `copy_degradation_10s`
- `copyability_score`

## Entry Jump

Entry jump, liderin buy fiyatı ile follower’ın gecikmeli buy fiyatı arasındaki farktır.

Örnek:

- Lider fiyatı: `1.00`
- 10 saniye sonra follower fiyatı: `1.30`
- Entry jump: `%30`

10 saniyede fiyat sürekli `%30+` zıplıyorsa cüzdan “geç girince tepeden aldırıyor” kabul edilir ve ağır ceza alır.

## Cüzdan Skoru

Varsayılan ağırlıklar:

| Bileşen | Ağırlık | Anlam |
|---|---:|---|
| copyability | %25 | 0.01 SOL ile gecikmeli kopya sonucu |
| performance | %15 | Liderin kendi win rate, PF ve örneklem kalitesi |
| consistency | %15 | Tutar tutarlılığı ve makul frekans |
| risk | %15 | Drawdown ve tek işlem kâr yoğunluğu |
| organic | %10 | Transfer gürültüsü, sniper/scalper cezaları |
| hold_quality | %5 | Medyan tutma ve kısa hold oranı |
| safety | %10 | rug/copy/insider güvenlik skoru |
| recency | %5 | Son işlem güncelliği |

Toplam puan confidence ile nötr `50` değerine doğru çekilir. Az veri varsa yüksek skor otomatik verilmez.

## Copyability Eligibility

Geçmiş gün sayısı artık takip için zorunlu kriter değildir. Cüzdan 30 günlük
geçmişe sahip değil diye elenmez; karar örneklem, copyability ve risk metrikleriyle
verilir.

Güncel canlı/elite politika daha serttir. Cüzdanın takip/live tarafında iyi sayılması
için artık yalnızca lider PnL yetmez; 10 saniye gecikmeli 0.01 SOL copy sonucu da
pozitif ve yeterli örneklemli olmalıdır.

Varsayılan live/elite eşikler:

- `closed_positions >= 12`
- `token_diversity >= 6`
- `realized_pnl_sol > 0`
- `profit_factor >= 1.20`
- `median_hold_seconds >= 300`
- `short_hold_ratio <= 0.45`
- `largest_trade_pnl_share <= 0.55`
- `days_since_last_trade <= 3`
- `copy_sample_size >= 12`
- `copyability_score >= 65`
- `copy_pnl_10s_sol > 0.001`
- `copy_profit_factor_10s >= 1.40`
- `avg_entry_jump_10s <= 0.15`
- `copy_coverage_ratio >= 0.70`
- `sniper_confidence <= 0.45`
- `scalper_confidence <= 0.45`
- `related_tracked_wallet_count = 0`: takip edilen başka cüzdanla SOL/token transfer bağı olmamalı.

Canlı işlem kapısı ek olarak şunları ister:

- `live_min_confluence = 1`: confluence kapalıdır; 2. cüzdan beklenmez.
- `live_max_token_age_minutes = 180`: 3 saatten eski token alınmaz.
- `live_min_token_age_seconds = 30`: pool/fiyat oturmadan ilk saniyelerde alınmaz.
- `live_require_known_token_age = true`: token yaşı bilinmiyorsa canlı alım açılmaz.
- Token değerlendirmesi veya güvenilir giriş fiyatı alınamazsa canlı alım fail-closed olur.
- Cüzdan son analizinde başka takip cüzdanıyla fon/token transfer bağı taşıyorsa canlı alım açılmaz.

Sample yetersizse sistem patlamaz; fakat canlı/elite filtrede takip için yeterli
sayılmaz. Bu, verisi az cüzdanın gerçek parayla işlem açtırmasını engeller.

## Culling

`culling.py` artık lider PnL’den çok copyability’ye bakar.

Sıralama önceliği:

1. `copyability_score`
2. `copy_pnl_10s_sol`
3. `latest_score`
4. `realized_pnl_sol`

Preset davranışı:

- `elite`: takip listesini en fazla 40 cüzdana indirir; pozitif 10sn copy PnL,
  copy score, copy PF, entry jump, hold süresi ve aktiflik şarttır.
  Ek olarak, birbirine SOL/token göndermiş cüzdanlardan yalnızca en yüksek rank'lı
  olan kalır; bağlı olanlar `below_threshold` yapılır.
- `strict`: yeterli sample varsa `copy_pnl_10s_sol > 0` zorunludur.
- `balanced`: yeterli sample varsa `copy_pnl_10s_sol >= 0` beklenir; yetersiz veri review kabul edilir.
- `light`: daha gevşek, temel uyuyan/zarar eden filtreleri uygular.

Leaderboard'daki `Sıfırla + Elite Rebuild` işlemi:

1. Mevcut `tracked` cüzdanları `below_threshold` durumuna alır.
2. Aday cüzdanlarda Helius/RPC geçmişini tarayıp SOL/token transfer bağlarını kaydeder.
3. DB'de kayıtlı swap verisi olan cüzdanları yeni elite kriterlerle yeniden puanlar.
4. `elite` culling uygular.
5. Eşik ve canlı risk ayarlarını elite copyability politikasına çeker.

Not: Eski DB swap kayıtlarından cüzdanlar arası SOL/token transfer bağı güvenilir
çıkarılamaz. Bu yüzden rebuild sırasında ilişki taraması zincire gider ve Helius/RPC
kredisi harcayabilir.

## Leaderboard

Leaderboard açıklaması ve sıralaması copyability’ye göre güncellenmiştir:

> Lider performansı + 0.01 SOL gecikmeli copy simülasyonu.

Varsayılan sıralama:

1. `copyability_score`
2. `copy_pnl_10s_sol`
3. `score`

Gösterilen yeni alanlar:

- Copy Score
- 10s Copy PnL
- 30s Copy PnL
- Entry Jump 10s
- Copy PF 10s
- Coverage
- Copy Sample

## Performance Sayfası

Performance sayfası gerçek paper sonuçlarını göstermeye devam eder. Ek olarak cüzdan bazında:

- `copyability_score`
- `pretrade_copy_pnl_10s`
- `real paper pnl`

yan yana gösterilir. Böylece geçmiş simülasyon ile canlı paper sonucu karşılaştırılır.

## Lider Elde Tutma Bekçisi

Canlı/paper akışta liderin sell olayı WS veya poll tarafında kaçabilir. Bu durumda
bizim pozisyon açık kalır ve token rug çekerse kayıp büyür. `leader_hold_watch.py`
servisi bu boşluğu kapatır.

Davranış:

1. Açık copy pozisyonlarını `LiveTrade` kayıtlarından çıkarır.
2. Her pozisyon için kopyalanan lider cüzdanın anlık SPL token hesabını okur.
3. Liderin token bakiyesi sıfır/dust ise veya aldığı miktarın çok küçük bir kısmına
   düştüyse lider tokenden çıktı kabul edilir.
4. Canlı modda PumpPortal üzerinden `%100 sell` gönderir.
5. Paper modda istenirse pozisyonu paper olarak kapatır.
6. Sonuçlar `leader_watch` kategorisiyle Loglar sayfasına yazılır.

Varsayılan risk ayarları:

- `leader_hold_watch_enabled = true`
- `leader_hold_grace_seconds = 20`
- `leader_hold_cooldown_seconds = 20`
- `leader_hold_zero_threshold = 1e-9`
- `leader_hold_exit_ratio = 0.05`
- `leader_hold_exit_confirmations = 1`
- `leader_hold_max_positions_per_run = 30`
- `leader_hold_watch_paper = false`

Bu servis sell sinyalini bekleyen ana mirror akışının yerine geçmez; onu tamamlayan
ikinci güvenlik ağıdır. Veri okunamazsa fail-closed davranır: yanlış satış yapmamak
için kapatma göndermez, log yazar.

## BUILD 60 — AI TRADE / COPY TRADE ayrımı

Sistemde iki strateji modu vardır:

- `strategy_mode=copy`: Takip edilen cüzdanın alım/satımını yansıtır. Cüzdan filtresi, copyability skoru, sniper/scalper filtresi, ilişki filtresi ve leader-watch aynen çalışır.
- `strategy_mode=ai`: Cüzdan ana karar değildir. PumpPortal taze token akışındaki alım eventleri token fırsatı olarak değerlendirilir. Bu modda token yaşı, token skoru, güvenilir fiyat ve güvenlik vetosu öne çıkar.

AI Trade gerçek para için ayrıca `ai_live_enabled=true` gerektirir. Bu kilit kapalıysa live mod açık olsa bile AI sinyalleri gerçek emir göndermez; önce paper sonuçları izlenmelidir.

## BUILD 61 — Mod Bazlı Arayüz

Bu sürümde trading motorundan çok panel organizasyonu değişmiştir.

- Ana sayfa iki mod seçimiyle açılır: `AI TRADE` ve `COPY TRADE`.
- Yan menü aktif moda göre sadeleşir.
- AI modunda cüzdan sayfaları gizlenir; AI panelinde paper bütçe, işlem kartları ve karar akışı görünür.
- Copy modunda cüzdan sıralaması, copy performansı ve leader-watch odaklı sayfalar görünür.
- Risk ayarları aktif moda göre bölümlenir ve her önemli ayar `?` açıklamasıyla anlatılır.

Bu değişiklik strateji motorunu bozmaz; kullanıcı arayüzünü daha anlaşılır hale getirir.


## BUILD 62 — Mod İzolasyonu ve AI Otomatik Yönetim

- `strategy_mode=ai` iken copy/cüzdan motorları arka planda çalışmaz. Takip edilen cüzdan poll, cüzdan keşfi, backlog analizi, prune, leader-watch ve copy yansıtma görevleri erken çıkar.
- `strategy_mode=copy` iken AI token motoru işlem üretmez.
- AI Trade varsayılan olarak `ai_auto_manage=true` ile çalışır. Token yaşı, token kapısı, skor eşiği ve fiyat şartı kullanıcıdan tek tek beklenmez; `ai_risk_profile` etkin policy üretir.
- AI risk profilleri:
  - `safe`: daha az işlem, yüksek skor, daha uzun minimum yaş.
  - `balanced`: önerilen varsayılan.
  - `opportunistic`: daha fazla paper denemesi, daha düşük skor kapısı.
- Manuel AI yaş/skor/fiyat ayarları yalnızca `ai_auto_manage=false` veya UI'da gelişmiş override açıldığında anlamlıdır.
- AI kararları `trading/decision-funnel` endpointiyle huniye dökülür; alım açma ve almama sebepleri ana panelde görünür.

## BUILD 69 — AI Fresh Launch Universe

AI Trade modunda sistem artık eski tokenleri ana fırsat evrenine dahil etmez. Bu, manuel bir "copy token yaşı" filtresi gibi değil, AI'ın kendi fırsat seçimi olarak uygulanır. Amaç 7-24 saat önce açılmış, hareketi daralmış tokenlarda küçük oynama kovalamak yerine yeni launch/pump potansiyeli olan tokenlara odaklanmaktır.

Varsayılan otomatik profiller:

- Güvenli: daha kısa ve seçici taze pencere.
- Dengeli: günlük kullanım için önerilen taze pencere.
- Fırsatçı: daha geniş ama hâlâ taze token odaklı pencere.

Eski token AI tarafından alınmazsa loglarda `AI fırsat evreni dışında` sebebiyle görünür ve Neden Almadım hunisine dahil olur.


## BUILD 70 — AI Fast Token Scanner

AI Trade token yakalama tarafında PumpPortal hızlı akışı varsayılan hale getirildi. WebSocket okuma döngüsü artık token analizini beklemez; olaylar kuyruk işçileriyle paralel işlenir. İzlenen taze token kapasitesi 1500'e çıkarıldı, yaş penceresi dolan tokenlar abonelikten atılır. Amaç yeni tokenleri kaçırmadan yakalamak, eski/gecikmiş sinyalleri ise kuyruğa yığmadan düşürmektir.

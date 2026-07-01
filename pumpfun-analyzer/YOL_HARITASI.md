# YOL HARİTASI — Projeyi bitirip temiz bir TEST aşamasına alma

Amaç: paneli "gerçek parayla küçük bakiyede güvenle test edilebilir" seviyeye
getirmek. Aşağıdaki liste **fazlara** bölünmüştür; her madde: **durum · efor ·
risk**. AI TRADE bölümü bilinçli olarak en yoğun bölümdür (mod yeni yapıldı).

Durum etiketleri: ✅ bitti · 🔧 kısmen var, iyileştirme gerek · 🆕 yeni iş
Efor: S (saatler) · M (1-2 gün) · L (2+ gün)

---

## FAZ 0 — Teste almadan önce OLMAZSA OLMAZLAR (blocker)

| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| 0.1 | Veri sağlayıcı sağlık paneli + degraded/down uyarısı | ✅ (b75-76) | — |
| 0.2 | Kötü veriyle işlem yapma fail-safe (tüm market down → alım dur) | ✅ (b76) | — |
| 0.3 | Ana ekran acil kill-switch | ✅ (b77) | — |
| 0.4 | **`.env` / anahtar hazırlık checklist ekranı** — HELIUS/PUMPPORTAL/BIRDEYE anahtarları var mı, hangi moddayız, tek ekranda "teste hazır mı?" yeşil/kırmızı | 🔧 (setup var, tek gauge yok) | S · düşük |
| 0.5 | **AI paper "sağlık sinyali"** — motor son X dk'da kaç token gördü, kaç sinyal, kaç alım/blok; 0 ise "neden sessiz?" tanısı | 🔧 (ai-center var) | S · düşük |

**Faz 0 çıkışı:** kullanıcı tek ekrandan "hangi moddayım, veri akıyor mu, motor
çalışıyor mu, canlı mıyım paper mı" sorusunu net görebiliyor.

---

## AI TRADE — YÜKSEK YOĞUNLUK 🎯

AI Trade bugün: PumpPortal firehose'undan gelen BUY/yeni-token olaylarını **lider
cüzdan aramadan** değerlendirir; her taze tokeni `score_token` ile puanlar; profil
(safe/balanced/opportunistic) yaş+skor+fiyat kapılarını otomatik yönetir; TP/SL/
trailing ile çıkar. Aşağısı bunu "sniper AI" seviyesine çıkarır.

### A) Sinyal & Fırsat Evreni
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| **A1** | **AI'ı Helius/Chainstack WS'e taşı** — pump.fun firehose (`logsSubscribe`) → AI motoru; PumpPortal'sız, SOL yakmadan | ✅ **build 81** | — |
| A1b | Yeni-token (create) olayına **doğrudan** tepki — en erken giriş penceresi | 🔧 (şimdi buy event'ine bakıyor) | M · orta |
| A2 | **Migration yakınlığı sinyali** — bonding curve % (pump → pumpswap geçişine ne kadar yakın). Pump.fun'da en güçlü 100x sinyallerinden | 🆕 | M · orta |
| A3 | **"Akıllı para" kesişimi** — bu tokeni bizim KÂRLI takip cüzdanlarımızdan alan var mı? AI + Copy zekâsını birleştirir (en yüksek değerli madde) | 🆕 | M · orta |
| A4 | Watchlist: migration'a tırmanan tokenleri izleyip eşik geçince tetikle | 🆕 | L · orta |

### B) Token Skorlama Kalitesi (motorun kalbi)
`score_token` bugün: security, holder_distribution, creator_history,
liquidity_quality, organic_growth, trade_behavior.
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| B1 | **Dev/creator cüzdan tutuş % + dev satış geçmişi** (rug öncü göstergesi) | 🔧 (creator_history var, derinleştir) | M · orta |
| B2 | **Top-10 holder yoğunlaşması** ceza eğrisi (insider kümesi) | 🔧 (holder_distribution var) | S · düşük |
| B3 | **Alıcı hızı / momentum** — dakikadaki benzersiz alıcı, buy/sell baskısı | 🔧 (trade_behavior var, netleştir) | M · orta |
| B4 | **LP burned/locked** kontrolü (likidite çekilebilir mi) | 🆕 | M · orta |
| B5 | Skor **breakdown kartı** — token neden yüksek/düşük aldı, her sinyalin katkısı UI'da | 🔧 (breakdown datası var, UI kartı yok) | S · düşük |
| B6 | Skor eşiklerini **gerçek sonuca göre kalibre** et (paper hit-rate → eşik önerisi) | 🆕 | M · orta |

### C) Giriş Kararı & Fail-safe
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| C1 | Token yaşı / skor / fiyat / likidite kapıları (profil bazlı) | ✅ | — |
| C2 | Güvenilir fiyat yoksa AI blok + tüm market down fail-safe | ✅ (b76) | — |
| C3 | **Duplicate/spam guard** — aynı tokene kısa sürede tekrar giriş engeli | 🔧 (sig dedup var, token-cooldown netleştir) | S · düşük |
| C4 | **Günlük AI bütçesi + max eşzamanlı AI pozisyonu** ayrı limit | 🔧 (genel limitler var, AI'a özel netleştir) | S · düşük |

### D) Çıkış Yönetimi (pump.fun hızlı — burada para kazanılır/kaybedilir)
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| D1 | Sabit TP / SL / trailing / max-hold | ✅ (position_manager) | — |
| D2 | **Kademeli çıkış (partial exit ladder)** — +%X'te %50 sat, kalanı trailing ile taşı | 🆕 | M · orta |
| D3 | **AI pozisyon watchdog** — likidite çekildi / dev dumped → TP/SL beklemeden acil çıkış | 🆕 (copy'de leader_hold_watch var, AI'a yok) | M · orta |
| D4 | Çıkış sebebini karar akışında göster (hangi kural neden tetikledi) | 🔧 (log var, kart netleştir) | S · düşük |

### E) Açıklanabilirlik & Test Paneli
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| E1 | "Neden aldı / neden almadı" akışı + "neden almadım hunisi" | ✅ (b73) | — |
| E2 | **AI Paper Karne** — seçili dönemde: hit-rate, ort. PnL, medyan tutma, en iyi/kötü işlem, "canlıya hazır mı?" göstergesi | 🔧 (ai-center kısmi) | M · düşük |
| E3 | Token skor breakdown kartı (B5 ile aynı) | 🔧 | S · düşük |

### F) Canlıya Geçiş Güvenliği
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| F1 | `ai_live_enabled` ayrı kilit (paper doğrulanmadan canlı yok) | ✅ | — |
| F2 | Küçük bakiye + günlük zarar limiti + kill-switch | ✅ | — |
| F3 | **"Canlıya geç" sihirbazı** — paper karne yeşilse tek akışta canlı kilidi aç | 🆕 | S · düşük |

---

## COPY TRADE (büyük ölçüde hazır — birkaç ekleme)
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| CP1 | Copyability skorlama + canlı copyability kapıları | ✅ (b74) | — |
| CP2 | Sniper/scalper canlı bloğu, leader-watch çıkış | ✅ | — |
| CP3 | **Küme/insider risk rozeti** leaderboard'da (`wallet_relationships`+`insider`/`rugger` var, yüzeye çıkmıyor) | 🔧 | M · düşük |
| CP4 | Otomatik cüzdan eleme (PnL bazlı) | ✅ | — |

---

## ORTAK ALTYAPI
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| I1 | Veri sağlayıcı sağlık omurgası | ✅ (b75) | — |
| I2 | **İkinci market kaynağı (Jupiter/Moralis) otomatik yedek** — DexScreener down olunca devreye girsin | 🆕 | M · orta |
| I3 | **On-chain portföy uzlaştırma** (TRADING_WALLET_ADDRESS ile gerçek bakiye/ghost pozisyon temizliği) | 🔧 (wallet_portfolio var) | M · orta |
| I4 | Derin cüzdan verisi için Helius anahtarı önerisi (public RPC zayıf halka) | dokümante | S · düşük |
| I5 | Repo geneli satır sonu normalize (`.gitattributes` eol=lf) | 🆕 | S · düşük |

---

## UI / UX & TEST HAZIRLIĞI
| # | Madde | Durum | Efor·Risk |
|---|-------|-------|-----------|
| U1 | HelpTooltip kritik ayarlarda | ✅ (b77 + b73) | — |
| U2 | Benzer sayfaları (`/paper`,`/live`,`/positions`,`/history`) tek "Portföy"de topla | 🆕 | M · düşük |
| U3 | PWA/manifest — telefondan "ana ekrana ekle" | 🆕 | S · düşük |
| U4 | Boş/yükleniyor/hata durum ekranları tutarlılığı | 🔧 | S · düşük |

---

## ÖNERİLEN UYGULAMA SIRASI (teste en hızlı yol)

**Sprint 1 — "Teste hazır" (AI odak, ~2-3 gün):**
0.4, 0.5 → **E2 (AI Paper Karne)** → **B5 (skor breakdown kartı)** → C3/C4 (AI
limit netleştirme). Bu blok bittiğinde: AI paper'ı açıp "sağlıklı sinyal üretiyor
mu, kararları mantıklı mı, canlıya hazır mı" sorusunu NET yanıtlayabilirsin.

**Sprint 2 — "AI kaliteyi yükselt" (~3-4 gün):**
A3 (akıllı para kesişimi) → A2 (migration yakınlığı) → D2 (kademeli çıkış) →
D3 (AI watchdog). AI'ın giriş isabetini ve çıkış korumasını ciddi artırır.

**Sprint 3 — "Dayanıklılık & canlı" (~2-3 gün):**
I2 (ikinci market kaynağı) → I3 (portföy uzlaştırma) → F3 (canlıya geç sihirbazı)
→ CP3 (küme rozeti). Canlıya güvenli geçiş + copy tarafını da tamamlar.

**Sprint 4 — "Cila" (opsiyonel):** U2, U3, I5, B6.

> Not: Sprint 1 tek başına projeyi "küçük bakiyeyle canlı test edilebilir" yapar.
> Sprint 2 kâr isabetini yükseltir. 3 dayanıklılık/otomasyon, 4 kozmetik.

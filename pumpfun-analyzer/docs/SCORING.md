# Puanlama Formülleri ve Eleme Kuralları

Tüm puanlar 0–100 aralığına sıkıştırılır (`clamp`). Ağırlıklar ve eşikler
`settings` tablosundan (panel) değiştirilebilir. Kaynak:
`backend/app/core/scoring/`.

> Düşük örneklemde **güven (confidence)** düşer ve nihai puan nötr 50 değerine
> doğru çekilir: `total = raw_total * confidence + 50 * (1 - confidence)`. Böylece
> az veriyle yüksek puan üretilmez.

---

## 1. PnL ve metrikler (FIFO)

Kaynak: `core/analysis/pnl.py`. Maliyet yöntemi **FIFO**:

- Her **alış** bir lot olur: `(miktar, maliyet = sol_amount + fee)`.
- Her **satış** en eski lotlardan tüketir:
  `pnl = (satış_geliri − fee) × pay − tüketilen_lot_maliyeti`.
- **Açık pozisyonlar** kazanılmış işlem **sayılmaz**; başarı oranı ve gerçekleşmiş
  PnL yalnızca kapanmış kısımlardan hesaplanır.
- **Gerçekleşmemiş PnL**, mevcut fiyat verilirse ayrı raporlanır.

Hesaplanan metrikler: kapalı pozisyon sayısı, başarı oranı, ortalama/medyan tutma
süresi, gerçekleşmiş/gerçekleşmemiş PnL, **profit factor** (brüt kâr / brüt
zarar), ortalama kazanç-zarar oranı, **maksimum düşüş** (kümülatif kâr eğrisi
tepe-dip), işlem başına risk, token çeşitliliği, işlem sıklığı, tutar tutarlılığı
(1 − değişim katsayısı), kısa-tutma oranı (<10 dk), tek işlemin toplam kârdaki
payı.

---

## 2. Cüzdan puanı (100 üzerinden)

| Bileşen | Ağırlık | Nasıl hesaplanır (özet) |
|---|---|---|
| performance | %25 | `0.5·win_rate·100 + 0.3·profit_factor_norm + 0.2·örneklem_norm` |
| consistency | %20 | `0.6·tutar_tutarlılığı·100 + 0.4·frekans_makullüğü` |
| risk | %15 | `100·(1 − 0.6·drawdown_oranı − 0.4·tek_işlem_yoğunlaşması)` |
| organic | %15 | `100 − transfer_gürültüsü·40 − sniper·50 − scalper·40` |
| hold_quality | %10 | medyan tutma bandı (30 dk–24 s ideal) − kısa-tutma cezası |
| safety | %10 | `100·(1 − max(rugger, copy, insider))` |
| recency | %5 | `100 − son_işlemden_geçen_gün·3` |

### Uygunluk (eleme) kuralları — varsayılan, panelden değiştirilebilir
- En az **20** kapanmış pozisyon
- En az **10** farklı token
- En az **30** günlük geçmiş
- Ücretler sonrası **≥ %60** başarı oranı
- Medyan tutma süresi **≥ 30 dk**
- **<10 dk** kapanan işlem oranı **≤ %35**
- Tek işlem toplam kârın aşırı büyük (>%60) bölümünü oluşturmamalı

### Kritik veto (puandan bağımsız ret)
Token oluşturucusu olma; yüksek (≥0.7) rugger / copy-trader / insider / sniper
güveni.

**Takip koşulu:** `total ≥ 70` **ve** veto yok **ve** tüm uygunluk kuralları
sağlanıyor.

---

## 3. Sınıflandırıcılar

Kaynak: `core/classification/`.

- **Copy-trader** (`copy_trader.py`): token örtüşmesi, yön benzerliği, **medyan
  takip gecikmesi**, miktar benzerliği ve **birkaç farklı token üzerinde tekrar**
  birleştirilerek 0–1 güven üretilir. Karar **tek bir benzer işleme** dayanmaz
  (varsayılan: ≥4 eşleşme ve ≥3 farklı token). Gerekçeler arayüzde gösterilir.
- **Rugger** (`rugger.py`): analiz edilen tokenin oluşturucusu olma, geçmiş
  rug/terk oranı, takipçilere dump, çok sayıda kısa ömürlü token.
- **Sniper/scalper** (`sniper.py`): token doğumundan ≤20 sn alım oranı, ilk-blok
  alımları, <5 dk kapanış oranı.
- **Insider/sybil** (`insider.py`): ortak fonlama kaynağı, eşzamanlı alım oranı,
  küme büyüklüğü, ortak token oranı.

---

## 4. Token puanı (100 üzerinden)

| Bileşen | Ağırlık | Özet |
|---|---|---|
| security | %30 | mint/freeze yetkisi, metadata değiştirilebilirliği, honeypot/satılabilirlik |
| holder_distribution | %20 | ilk 10 yoğunluk, insider arzı, sniper oranı, benzersiz holder |
| creator_history | %15 | creator rug geçmişi, önceki token sayısı |
| liquidity_quality | %15 | likidite (aşamaya göre ölçek), sahte likidite |
| organic_growth | %10 | holder büyüme hızı, alıcı/satıcı dengesi |
| trade_behavior | %10 | wash trading, ani satış riski |

> LP, bonding curve ve sistem cüzdanları holder hesabından **ayrılır**.
> Bonding aşamasındaki çok yeni tokenler mezun tokenlerle aynı likidite/holder
> beklentisine tabi tutulmaz (aşamaya uyarlı puanlama + düşük güven).

### Kritik veto (puandan bağımsız)
Aktif/tehlikeli **mint** veya **freeze** yetkisi; doğrulanmış **rugger creator**;
**aşırı insider arzı** (≥%50); **honeypot/satılamama**; **sahte likidite**; çok
kuvvetli **wash trading** (≥0.8).

**Takip koşulu:** `total ≥ 70` **ve** veto yok.

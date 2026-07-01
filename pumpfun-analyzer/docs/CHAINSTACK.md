# Chainstack Entegrasyonu (Helius / PumpPortal yerine)

Amaç: derin zincir verisini (cüzdan geçmişi, token güvenliği, keşif) ve gerçek-zamanlı
akışı **Helius kredisi bitmeden / PumpPortal SOL yakmadan** Chainstack üzerinden almak.

Chainstack **standart Solana JSON-RPC + WebSocket** verir. Kodumuz zaten bu standart
metodları kullanır (`getSignaturesForAddress`, `getTransaction`, `getAccountInfo`,
`logsSubscribe`, …), bu yüzden **kod değişikliği gerekmez** — sadece `.env`.

---

## 1) Chainstack'te node oluştur (site kafa karıştırıcı, sırayla)

Chainstack'te "sadece API key" değil, **bir node endpoint'i** alırsın:

1. https://console.chainstack.com → giriş.
2. Sol menü **Projects** → bir proje yoksa **Create project** (Public chains).
3. Proje içinde **Get started / Add node** → ağ seç:
   - **Blockchain:** Solana
   - **Network:** Mainnet
   - **Type:** Public/Global (Shared) — free kredi bununla kullanılır.
4. Deploy et, node **Running** olana kadar bekle (~1 dk).
5. Node'a tıkla → **Access and credentials** sekmesi. Burada şunları görürsün:
   - **HTTPS endpoint** — örn. `https://solana-mainnet.core.chainstack.com/XXXXXXXXXXXXXXXX`
   - **WSS endpoint** — örn. `wss://solana-mainnet.core.chainstack.com/XXXXXXXXXXXXXXXX`
   - (Bazı planlarda ayrıca **Username / Password** gösterilir — aşağıda "Auth" notu.)

> ⚠️ En sık hata: "API key"i tek başına `SOLANA_RPC_URL`'e yazmak. Gerekli olan
> **tam endpoint URL'i** (token zaten URL'in içinde gömülü). Yukarıdaki HTTPS/WSS
> URL'lerini OLDUĞU GİBİ kopyala.

---

## 2) `.env` ayarları (tam olarak bunlar)

```dotenv
# Helius'u DEVRE DIŞI bırak (anahtar doluysa kod Helius'a döner)
HELIUS_API_KEY=
HELIUS_RPC_URL=
HELIUS_WS_URL=

# Chainstack endpoint'leri (Access and credentials'tan TAM URL)
SOLANA_RPC_URL=https://solana-mainnet.core.chainstack.com/XXXXXXXXXXXXXXXX
SOLANA_WS_URL=wss://solana-mainnet.core.chainstack.com/XXXXXXXXXXXXXXXX

# Dinleyici: Helius/RPC WS (logsSubscribe). Anahtar yok → SOLANA_WS_URL'e düşer = Chainstack WS
LISTENER_PROVIDER=helius

# Rate limit: dedicated değilse yavaşlarsa yükselt
RPC_MIN_INTERVAL_SECONDS=0.02
RPC_RATE_LIMIT_RETRIES=8
```

**Auth notu:** Node'un credentials ekranı **Username/Password** gösteriyorsa (token
URL'de değilse), URL'e göm:
```
SOLANA_RPC_URL=https://USERNAME:PASSWORD@solana-mainnet.core.chainstack.com
SOLANA_WS_URL=wss://USERNAME:PASSWORD@solana-mainnet.core.chainstack.com
```
Kod (httpx + websockets) bu formatı destekler.

Sonra: `docker compose up -d --build`

---

## 3) Doğrulama (çalışıyor mu?)

**a) RPC — terminalden hızlı test:**
```bash
curl -s -X POST "$SOLANA_RPC_URL" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
# Beklenen: {"jsonrpc":"2.0","result":"ok","id":1}
```

**b) Panelden:**
- **Sistem Sağlığı** → `Zincir Sağlayıcı` = **rpc**, "Veri Sağlayıcı Sağlığı" kartında
  `rpc` sağlayıcı **yeşil** ve düşük gecikme.
- **Teknik Loglar** → `[LISTENER] Helius WS connected` benzeri satır (WS bağlandı).
  Ardından takip/keşif olayları akmaya başlar.

**c) WebSocket (logsSubscribe) — ÖNEMLİ NOT (build 82 ile çözüldü):**
Chainstack shared node'u `logsSubscribe`'ı **`mentions` filtresiyle DESTEKLEMEZ**
(aboneliği kabul eder ama hiç bildirim göndermez). Sadece `logsSubscribe "all"` çalışır.
Bizim dinleyicimiz bunu otomatik halleder: **`WS_LOGS_MODE=auto`** (varsayılan) →
Helius anahtarı yoksa **"all"** modunu seçer → tüm logları alıp **pump.fun'ı
client-side filtreler**. Böylece copy + AI Chainstack'te çalışır. (Canlı Chainstack
verisiyle uçtan uca doğrulandı.)

Maliyet notu: "all" modu daha çok WS bant genişliği kullanır (tüm Solana logları),
ama getTransaction yalnız pump.fun işlemlerine yapılır (rate-limitli) → RPC kredisi
kontrollü, SOL harcanmaz.

---

## 3.5) ⚠️ Chainstack FREE plan kısıtı: getSignaturesForAddress (arşiv/403)
Chainstack free/global plan `getSignaturesForAddress`'i "Archive" sayıp **403 /
-32002** ile reddeder (cüzdan/token geçmiş analizinde kullanılır). **Build 83 bunu
otomatik çözer:** bu metod, plan limiti görülünce **metod-bazlı olarak yedek RPC'ye**
(`SOLANA_RPC_FALLBACK_URL`, varsayılan public mainnet-beta) yönlendirilir; Chainstack
diğer metodlarda (getTransaction, getAccountInfo, getTokenLargestAccounts…) kullanılmaya
devam eder. Yani ekstra ayar gerekmez — public fallback varsayılan açık. İstersen
`SOLANA_RPC_FALLBACK_URL`'i başka bir ücretsiz RPC yapabilirsin.

Canlı doğrulandı: getSignaturesForAddress → public (200), getTransaction → Chainstack (200).

## 4) Ne %100 çalışır, ne iş gerektirir (dürüst tablo)

| İş | Chainstack ile | Not |
|---|---|---|
| Derin cüzdan analizi / skorlama | ✅ %100 | Standart RPC; public 503'leri biter |
| Cüzdan keşfi (discovery) | ✅ %100 | RPC + WS logsSubscribe |
| **COPY Trade (gerçek-zamanlı)** | ✅ %100 | WS logsSubscribe(mentions=cüzdan); PumpPortal/SOL yok |
| Token güvenlik/likidite verisi | ✅ | Fiyat DexScreener'dan (ayrı, anahtarsız) |
| **AI Trade (geniş yeni-token evreni)** | ✅ (build 81 / A1) | Aşağıya bak |

### AI Trade — A1 ile Chainstack üzerinde çalışır (build 81)
Artık `helius_listener` AI modunda pump.fun firehose'unu (`logsSubscribe
mentions=[PUMP_FUN_PROGRAM]`) **AI token-fırsat motoruna route eder** (`build_ai_trades`
→ `handle_trade_event` is_ai_signal). Yani AI Trade, PumpPortal firehose'u OLMADAN,
Chainstack/Helius WS üzerinden çalışır — **SOL yakmadan (RPC kredisi).**

Kurulum notları (AI'ı Chainstack WS'te çalıştırmak için):
- `PUMPPORTAL_API_KEY=` **BOŞ** olmalı. (Doluysa `auto`/varsayılan seçim AI'da
  PumpPortal'ı tercih eder — parse edilmiş, getTransaction'sız olduğu için ucuzdur.)
- `LISTENER_PROVIDER=helius` (açık seçim AI modunda da RESPECT edilir; artık
  PumpPortal'a zorlanmaz).
- `SOLANA_WS_URL` = Chainstack WSS endpoint.
- Keşif akışı (firehose) AI modunda otomatik açılır; AI değerlendirme hızı
  `DISCOVERY_MAX_LOOKUPS_PER_MIN` ile sınırlıdır (RPC bütçesi). Chainstack'te bunu
  yükseltebilirsin.

Maliyet notu: PumpPortal parse edilmiş event verir (getTransaction gerekmez);
logsSubscribe yolu her aday için `getTransaction` çeker → daha çok RPC kredisi. Bu
yüzden AI değerlendirmesi dakikalık limitle korunur. Chainstack'in yüksek RPS'i bunu
rahatça kaldırır; SOL harcanmaz.

---

## 5) Özet karar
- **Şimdi:** Chainstack'i yukarıdaki gibi bağla → derin veri + COPY %100 SOL-free çalışır,
  Helius/PumpPortal gerekmez.
- **AI için:** A1 (pump.fun log → AI motoru) yapılınca AI de Chainstack'te tam çalışır.
  Chainstack bağlanıp WS doğrulandıktan sonra bunu uygularım.

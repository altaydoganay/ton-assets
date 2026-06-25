# Pump.fun Cüzdan & Token Analizcisi

Solana ve Pump.fun ağı üzerinde **başarılı cüzdanları ve tokenleri** davranışsal
kalite, tutarlılık, risk kontrolü ve organik işlem geçmişine göre keşfeden,
puanlayan; Telegram bildirimi gönderen ve **isteğe bağlı** kopya işlem
(paper / canlı) yapabilen tam kapsamlı bir uygulama.

> ⚠️ **Sorumluluk reddi:** Bu yazılım hiçbir kârlılık garantisi vermez. Kripto
> işlemleri yüksek risklidir. Tüm analizler veri yeterliliği ve güven seviyesiyle
> birlikte sunulur; eksik/doğrulanmamış veri kesin bilgi gibi gösterilmez.
> "Başarılı cüzdan" yalnızca çok kazanan değil; tutarlı, düşük riskli ve organik
> davranan cüzdandır.

---

## İçindekiler
- [Mimari](#mimari)
- [Hızlı başlangıç (Docker)](#hızlı-başlangıç-docker)
- [Yerel geliştirme](#yerel-geliştirme)
- [Ortam değişkenleri](#ortam-değişkenleri)
- [Veri sağlayıcı (adapter) ayarları](#veri-sağlayıcı-adapter-ayarları)
- [Telegram bot kurulumu](#telegram-bot-kurulumu)
- [Otomatik kopya işlem ve güvenlik](#otomatik-kopya-işlem-ve-güvenlik)
- [Puanlama formülleri](#puanlama-formülleri)
- [Veritabanı şeması](#veritabanı-şeması)
- [Testler](#testler)
- [API dokümantasyonu](#api-dokümantasyonu)
- [Ek belgeler](#ek-belgeler)

---

## Mimari

Temiz, modüler bir monorepo:

```
pumpfun-analyzer/
├── backend/                  # Python FastAPI + SQLAlchemy + Alembic + Celery
│   ├── app/
│   │   ├── adapters/         # Veri sağlayıcı adapterleri (RPC, Helius, Birdeye, DexScreener, Pump.fun)
│   │   ├── core/
│   │   │   ├── analysis/     # PnL (FIFO), swap/transfer tespiti
│   │   │   ├── classification/  # rugger, copy-trader, sniper, insider tespiti
│   │   │   ├── discovery/    # aday cüzdan keşfi
│   │   │   └── scoring/      # cüzdan & token puanlama motorları
│   │   ├── trading/          # risk kuralları, paper trading, kopya işlem motoru
│   │   ├── notifications/    # Telegram + deduplication
│   │   ├── security/         # şifreli keystore + log maskeleme
│   │   ├── services/         # orkestrasyon (pipeline, ayarlar, kalıcılaştırma)
│   │   ├── workers/          # Celery görevleri + WebSocket dinleyici
│   │   ├── api/              # FastAPI route'ları
│   │   ├── models.py         # 14 tablo
│   │   └── main.py
│   ├── alembic/              # migrationlar
│   └── tests/                # 62 test (pytest)
├── frontend/                 # Next.js 14 + TypeScript + Tailwind + Recharts
│   └── app/                  # 15 Türkçe sayfa (App Router)
├── docker-compose.yml        # db + redis + backend + worker + beat + frontend
└── .env.example
```

| Katman | Teknoloji |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind + Recharts + SWR |
| Backend | Python 3.11 + FastAPI + SQLAlchemy 2 |
| Veritabanı | PostgreSQL 16 (testlerde SQLite) |
| Kuyruk/Önbellek | Redis 7 |
| Arka plan görevleri | Celery (worker + beat) |
| Zincir takibi | Solana WebSocket (`logsSubscribe`) + JSON-RPC |
| Dağıtım | Docker Compose |

---

## Hızlı başlangıç (Docker)

```bash
cd pumpfun-analyzer
cp .env.example .env          # değerleri düzenleyin
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API + Swagger: http://localhost:8000/docs
- Migrationlar backend konteyneri açılışında otomatik uygulanır.

## Yerel geliştirme

**Backend** (harici servis olmadan, SQLite ile çalışabilir):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./data/app.db"   # veya PostgreSQL bağlantısı
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Frontend**:
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000/api npm run dev
```

**Celery (canlı takip/keşif için, Redis gerekir)**:
```bash
cd backend
celery -A app.workers.celery_app.celery_app worker --loglevel=info
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

---

## Ortam değişkenleri

Tüm gizli anahtarlar `.env` üzerinden yönetilir (örnek: `.env.example`). Hiçbir
anahtar kaynak koduna gömülmez. Öne çıkanlar:

| Değişken | Açıklama |
|---|---|
| `DATABASE_URL` | PostgreSQL bağlantısı (testte SQLite) |
| `REDIS_URL`, `CELERY_BROKER_URL` | Redis / kuyruk |
| `CHAIN_PROVIDER` | `rpc` veya `helius` |
| `MARKET_PROVIDER` | `dexscreener` (anahtarsız) veya `birdeye` |
| `SOLANA_RPC_URL`, `SOLANA_WS_URL` | RPC/WS uç noktaları |
| `HELIUS_API_KEY`, `BIRDEYE_API_KEY` | sağlayıcı anahtarları |
| `TELEGRAM_*` | Telegram bot ayarları |
| `TRADING_MODE` | `paper` \| `alerts_only` \| `live` |
| `LIVE_TRADING_CONFIRMED` | canlı işlem için açık onay |
| `KEYSTORE_PASSPHRASE`, `KEYSTORE_PATH` | şifreli trading cüzdanı kasası (yerel imzalama) |
| `PUMPPORTAL_API_KEY` | PumpPortal Lightning işlem anahtarı (canlı al-sat) |
| `PUMPPORTAL_DATA_WS` | PumpPortal canlı veri akışı (ücretsiz) |
| `LIVE_LISTENER_ENABLED` | canlı olay dinleyici servisi |
| `FRONTEND_PORT`, `BACKEND_PORT` | port çakışmasında değiştirin (örn. 3001) |

---

## Veri sağlayıcı (adapter) ayarları

Sağlayıcılar **adapter deseniyle** soyutlanmıştır (`app/adapters/`). Hangi
sağlayıcının kullanılacağı `.env` ve panelden (API/RPC Ayarları sayfası)
belirlenir. Yeni bir sağlayıcı eklemek için `ChainProvider` / `MarketProvider`
arayüzünü uygulamak yeterlidir.

- **Zincir verisi:** `HeliusAdapter` (ÖNERİLEN) veya `SolanaRpcAdapter`
  (failover'lı, birden çok endpoint sırayla denenir).
  - **Helius Enhanced Transactions (kredi kritik):** Cüzdan analizinde,
    imza-başına ayrı `getTransaction` yerine **Enhanced Transactions History**
    (`/v0/addresses/{adres}/transactions`) kullanılır — **tek HTTP isteğinde 100
    parse edilmiş işlem**. Bu sayede cüzdan başına ~100 RPC çağrısı **tek isteğe**
    iner (≈10× daha az kredi) ve daha **derin** geçmiş alınır; "8 kapalı pozisyon /
    4 farklı token" gibi eleme kriterleri gerçek trader'larca karşılanabilir hale
    gelir. `HELIUS_API_KEY` yoksa otomatik olarak standart RPC'ye düşülür.
- **Piyasa verisi:** `DexScreenerAdapter` (anahtarsız) veya `BirdeyeAdapter`.

**Pump.fun / PumpSwap:** Arayüz **scrape edilmez**. Öncelik zincir üstü veri ve
doğrulanmış program id'leridir (`app/adapters/pumpfun.py` ve
`core/analysis/swap_detection.py` içinde tek kaynaktan tutulur). Bonding curve →
PumpSwap mezuniyet durumu zincir verisinden çıkarılır.

---

## Telegram bot kurulumu

1. Telegram'da [@BotFather](https://t.me/BotFather) ile `/newbot` çalıştırıp bir
   bot oluşturun; size bir **token** verir.
2. Botunuzla bir sohbet başlatın (veya bir gruba ekleyin).
3. **Chat ID** öğrenmek için: bota mesaj atın, ardından
   `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini açın ve
   `chat.id` değerini alın.
4. `.env` dosyasına yazın:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=987654321
   ```
5. Bildirim koşulu: **puanı ≥ 70 takip edilen bir cüzdan**, **puanı ≥ 70 takip
   edilen bir tokeni satın aldığında** mesaj gönderilir. Aynı işlem için
   (transaction signature bazlı **deduplication**) tekrar bildirim gönderilmez;
   yeniden başlatma sonrasında da `alerts` tablosu sayesinde tekrar etmez.

Bildirim içeriği: cüzdan kısa adresi + adı, cüzdan puanı, token adı + contract,
token puanı, miktar, SOL/USD değeri, zaman, işlem linki, analiz linki, risk
uyarıları ve otomatik işlem yapılıp yapılmadığı.

---

## Otomatik kopya işlem ve güvenlik

**PAPER (simülasyon) motoru varsayılan olarak AÇIKTIR** — risksizdir, gerçek para
kullanmaz; takipteki bir cüzdan uygun bir token aldığında otomatik bir *kâğıt*
işlem açar ve `İşlem Geçmişi`/`Açık Pozisyonlar`da görünür. **CANLI (gerçek para)
işlem KAPALIDIR** ve ayrı bir onaya (`live_confirmed`) + keystore'a bağlıdır.
Bildirim sistemi ile işlem motoru **bağımsız** çalışır.

**İşlem kapısı (`token_gate`)** — token bir KALİTE notundan çok bir GÜVENLİK
filtresidir; çünkü kopya-ticarette asıl sinyal **cüzdandır** (akıllı para). Taze
pump.fun token'leri doğası gereği düşük "kalite" puanı alır (likidite/holder
verisi henüz oluşmamıştır), bu yüzden katı bir 70 eşiği neredeyse hiç işlem
açtırmaz. Üç politika (Risk Ayarları'ndan seçilir):
- **`balanced` (VARSAYILAN):** güvenlik vetosu (rug/honeypot/aktif mint-freeze)
  yok **ve** token puanı ≥ 55. *İşlem açılır ama "her token"de değil* — çöp/tek-
  holder bonding token'leri elenir, olgunlaşmış güvenli token'ler işlem açar.
- **`safety`:** yalnızca güvenlik vetosu (puan eşiği yok). En çok işlem; cüzdana
  tam güven. Daha agresif.
- **`score`:** güvenlik + tam `min_token_score` (klasik katı; çok az işlem).

**Modlar:** `paper` (tam simülasyon, varsayılan AÇIK) · `alerts_only` · `live`.
Canlı işlem yalnızca kullanıcı panelde riskleri onaylayıp (`live_confirmed`) ayrı
bir trading cüzdanı tanımladığında çalışır.

**Ayarlanabilir limitler** (Risk Ayarları sayfası): işlem başına sabit SOL veya
orantılı kopyalama, maksimum pozisyon, günlük harcama/zarar, maksimum slippage,
priority fee, minimum cüzdan/token puanı, token başına maks. açık pozisyon,
maksimum izleme gecikmesi, minimum likidite, engelleme listeleri, yalnızca seçili
cüzdanları kopyalama ve **acil durdurma**.

İşlem göndermeden hemen önce token güvenliği ve **satılabilirlik** yeniden
kontrol edilir; token puanı eşik altına düşmüşse işlem yapılmaz. Hedef cüzdan
kısmi satış yaparsa ayara göre **aynı oranda** satılır veya pozisyon tamamen
kapatılır. Transferler satış olarak yorumlanmaz; yalnızca gerçek swap'lar.

### Özel anahtar güvenliği
- Seed phrase / private key **frontend'e gönderilmez**, **log/DB/hata raporuna
  yazılmaz**, **düz metin saklanmaz**.
- Anahtar, uygulama parolasıyla türetilen anahtarla (PBKDF2-HMAC-SHA256, 480k
  iterasyon) **Fernet** ile şifrelenip yerel keystore'da tutulur; yalnızca
  imzalama anında çözülür (`app/security/keystore.py`).
- Tüm loglara **maskeleme filtresi** (`SecretRedactionFilter`) uygulanır; base58/
  hex secret, mnemonic ve `private_key=` benzeri kalıplar `[GIZLI]` ile değişir.
  Cüzdan **adresi** (public) maskelenmez.
- Arayüz, canlı işlem için **ayrı ve düşük bakiyeli** bir trading cüzdanı
  kullanılmasını belirtir; ana cüzdanla işlem teşvik edilmez.
- Acil durdurma butonu, "açık pozisyonları kapat" ile "yalnızca yeni işlemleri
  durdur" arasında seçim sunar.

---

## Canlı akış: cüzdan ekleme → bildirim → otomatik işlem

Uçtan uca akış (PumpPortal canlı veri + Helius zincir verisi ile):

1. **Otomatik keşif (varsayılan, Helius ile — ücretsiz).** `listener` servisi
   Helius WebSocket'inden (`logsSubscribe`, planına dahil, SOL ÜCRETİ YOK) pump.fun
   işlemlerini dinler, alıcıları çıkarır; birden fazla farklı token alan cüzdanlar
   *Keşfedilen Cüzdanlar* listesine `discovered` olarak otomatik eklenir. Ücretsiz
   Helius kotasını korumak için keşif sorguları `DISCOVERY_MAX_LOOKUPS_PER_MIN` ile
   sınırlıdır. (Eski PumpPortal akışı her olay için SOL ücreti kestiğinden artık
   yalnızca canlı al-sat için kullanılır; `LISTENER_PROVIDER=helius` varsayılandır.)
   Celery beat bunları parti parti (`DISCOVERY_INTERVAL_SECONDS`, varsayılan 3
   dakikada bir, `DISCOVERY_BATCH_SIZE` adet) Helius **Enhanced Transactions** ile
   DERİN (varsayılan 150 işlem) ve UCUZ analiz edip puanlar; puan ≥ 70 ve
   tüm kalite/eleme kriterlerini geçenler otomatik **takip listesine** alınır.
   İstersen *Keşfedilen Cüzdanlar* sayfasından **elle de** adres ekleyebilirsin
   (`POST /api/wallets`). Otomatik keşif `DISCOVERY_ENABLED=false` ile kapatılır.
2. **Dinleyici devreye girer.** `listener` servisi PumpPortal veri akışına
   (`wss://pumpportal.fun/api/data`) bağlanır ve takipteki cüzdanlara
   `subscribeAccountTrade` ile abone olur. Takip listesi otomatik tazelenir.
3. **Olay yakalanır.** Takipteki bir cüzdan bir tokeni **satın aldığında**, sistem
   o tokeni anlık analiz eder (mint/freeze yetkisi, likidite, ilk-10 yoğunluk).
   Token puanı ≥ 70 ve veto yoksa:
   - **Telegram bildirimi** gönderilir (signature bazlı dedup ile, tekrar yok),
   - **kopya işlem motoru** bağımsız tetiklenir (Telegram beklenmez).
4. **İşlem yürütülür** (moda göre):
   - `paper`: simülasyon, `paper_trades`'e kayıt (varsayılan, risksiz),
   - `live`: **PumpPortal Lightning API** ile gerçek al-sat — özel anahtar
     PumpPortal tarafında kalır, bizim loglarımıza/DB'mize girmez.
   Hedef cüzdan satış yaparsa pozisyon ayara göre yansıtılır.

**Canlı al-sat'ı açmak için** (gerçek para):
```
TRADING_MODE=live
LIVE_TRADING_CONFIRMED=true
PUMPPORTAL_API_KEY=...        # PumpPortal Lightning cüzdan anahtarınız
```
ve Risk Ayarları sayfasında **İşlem Motoru = Açık** + limitlerinizi belirleyin.
PumpPortal Lightning cüzdanına **düşük** bir bakiye yükleyin; ana cüzdanınızı
kullanmayın. Her işlem öncesi token güvenliği/satılabilirliği yeniden kontrol
edilir; **acil durdurma** her an yeni işlemleri durdurur.

> Not: Anlık token analizi v1'de "hafif"tir (zincir üstü güvenlik + piyasa
> likiditesi + ilk-N holder yoğunluğu). Tam holder de-etiketleme (LP/sistem
> ayrımı, insider/sniper arzı) düşük güven (confidence) ile işaretlenir ve
> ileride genişletilebilir — eksik veri kesin bilgi gibi sunulmaz.

### Sık karşılaşılan durumlar (SSS)

**"Çok cüzdan keşfedildi ama takip edilen çok az / hiç işlem yok."** Bu
genelde **normaldir ve tasarımın bir parçasıdır** — keşif "kim alım yapıyor"
sinyalini üretir; pump.fun'da bu havuz büyük oranda snipe/bot'tur ve kalite
filtreleri (puan ≥ 70 + eleme + veto + **veri yeterliliği/confidence**) bunları
doğru biçimde eler. Takip listesine yalnızca **tutarlı, çok-tokenli, organik**
geçmişe sahip cüzdanlar girer. Daha fazla nitelikli cüzdan yüzeye çıkması için:
> - `CHAIN_PROVIDER=helius` ve `HELIUS_API_KEY` ayarlı olsun — Enhanced
>   Transactions ile **derin** geçmiş alınır (sığ 50-işlem penceresi gerçek
>   trader'ların "8 kapalı pozisyon / 4 token" kriterini karşılayamaz).
> - Bütçen varsa `DISCOVERY_BATCH_SIZE` ve `DISCOVERY_INTERVAL_SECONDS` ile
>   analiz hızını artır (backlog daha hızlı erir).
> - Eşik/eleme/ağırlıklar panelden (API & Eşik Ayarları) gevşetilebilir; ama
>   gevşetmek kaliteyi düşürür.

**"İşlem (trade) hiç olmuyor."** Artık **PAPER motoru varsayılan AÇIK** (risksiz
simülasyon) ve işlem kapısı **`balanced`** olduğundan, takipteki bir cüzdan güvenli
ve makul (≥55) bir token aldığında otomatik bir kâğıt işlem açılır + Telegram
bildirimi gönderilir. Hâlâ işlem görmüyorsan sıra şu: (1) takip havuzunun aktif
cüzdan içermesi gerekir — uyuyan cüzdanlar alım yapmaz (bkz. yukarıdaki "az takip"
maddesi); (2) önceki katı sürümden gelen bir kayıt varsa Risk Ayarları'nda
**İşlem Motoru = Açık**, **Mod = paper**, **Kapı = balanced** olduğunu doğrula;
(3) daha çok işlem istiyorsan kapıyı **`safety`**'ye al (cüzdana tam güven, token
sadece rug filtresinden geçer). **Gerçek para** için: Mod = `live` + canlı onay +
keystore.

**"Kredi çok hızlı tükeniyor."** En büyük kalemler: (1) keşif `getTransaction`
sorguları → `DISCOVERY_MAX_LOOKUPS_PER_MIN` ile sınırla; (2) aday analizi →
`CHAIN_PROVIDER=helius` (Enhanced Transactions) ile imza-başına çağrı yerine tek
istek kullan, `DISCOVERY_BATCH_SIZE`/`DISCOVERY_INTERVAL_SECONDS` ile hızı bütçene
göre ayarla.

## Puanlama formülleri

Ayrıntılı formüller ve gerekçeler için **[docs/SCORING.md](docs/SCORING.md)**.
Özet:

**Cüzdan (100 üzerinden):** %25 işlem başarısı & örneklem · %20 tutarlılık ·
%15 risk/max düşüş · %15 organik davranış · %10 tutma süresi · %10 rug/copy/
insider güvenliği · %5 güncellik. Toplam ≥ 70 **ve** veto yok **ve** uygunluk
kuralları sağlanırsa takip listesine alınır.

**Token (100 üzerinden):** %30 zincir üstü güvenlik · %20 holder dağılımı ·
%15 creator geçmişi · %15 likidite/piyasa · %10 organik büyüme · %10 işlem
davranışı. Token yaşına/aşamasına (bonding vs mezun) göre uyarlanır.

Her iki motorda da **düşük örneklem güveni** nihai puanı nötr (50) değere doğru
çeker — az veriyle yüksek puan verilmez. Ağırlıklar panelden değiştirilebilir.

**PnL — maliyet yöntemi:** **FIFO** (ilk giren ilk çıkar). Ücretler (ağ +
priority + tip) alış maliyetine ve satış gelirine dahildir ("ücretler sonrası").
Açık pozisyonlar kazanılmış işlem sayılmaz; gerçekleşmemiş PnL ayrı raporlanır.

---

## Veritabanı şeması

14 tablo: `wallets`, `wallet_scores`, `wallet_relationships`, `tokens`,
`token_scores`, `token_holders`, `swaps`, `positions`, `alerts`, `paper_trades`,
`live_trades`, `settings`, `risk_rules`, `audit_logs`.

- **Puan geçmişi** `*_scores` tablolarında saklanır; her analizde yeni satır
  eklenir ve panelde grafiklenebilir.
- 70 puanın altına düşen kayıtlar **silinmez**; `below_threshold` durumuna
  alınır (yeni bildirim/işlem durur, geçmiş denetim için korunur).

Migration: `cd backend && alembic upgrade head`.

---

## Testler

62 test; harici servis gerekmez (SQLite ile çalışır):

```bash
cd backend && source .venv/bin/activate && pytest -q
```

Kapsam: FIFO PnL, swap/transfer ayrımı, cüzdan/token puanlama, veto kuralları,
rugger/copy-trader/sniper/insider sınıflandırma, Telegram deduplication, paper
trading, **kısmi satış**, RPC kesintisi/failover, **private key'in loglara
sızmadığı**, kopya işlem motoru güvenlik yeniden-kontrolü, API akışları ve
**gerçek para kullanmadan geçmiş işlem replay** (`tests/test_replay.py`).

---

## API dokümantasyonu

Çalışırken interaktif Swagger: **http://localhost:8000/docs**.
Özet uç noktalar için **[docs/API.md](docs/API.md)**.

---

## Ek belgeler
- [docs/SCORING.md](docs/SCORING.md) — puanlama formülleri ve eleme kuralları
- [docs/SECURITY.md](docs/SECURITY.md) — güvenlik mimarisi
- [docs/API.md](docs/API.md) — REST uç noktaları

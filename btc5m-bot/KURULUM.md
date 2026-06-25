# Kurulum ve Kullanım Rehberi (Türkçe)

> ⚠️ **ÖNEMLİ UYARI.** Bu stratejinin tüm testlerde **negatif beklenen değeri**
> var (bkz. `../btc5m-backtest/`). Gerçek parayla büyük olasılıkla **kaybedersin.**
> Ayrıca canlı emir yolu **gerçek fonla test edilmedi.** Önce demo ile öğren,
> canlıya geçersen kaybetmeyi göze alabileceğin en küçük miktarla başla. Bu bir
> yazılımdır, yatırım tavsiyesi değildir.

---

## 🔄 Güncelleme notu (neden artık işlem açıyor)
İlk sürüm, order book fiyatı **0.70**'e ulaşınca işlem açıyordu. Ama bu marketlerde
fiyat, kapanışa son saniyelere kadar **~0.50**'de duruyor; o yüzden BTC sakinken
hiç tetiklenmiyordu (saatlerce 0 işlem). Yeni varsayılan mod **`btc_move`**: BTC'nin
pencerenin açılış fiyatına (**strike**) göre hareketini gerçek zamanlı kullanır ve
hareket `move_threshold_usd`'yi (varsayılan 10$) geçince favori tarafa girer. Böylece
çoğu 5-dk penceresinde işlem açar. (Eski davranışı istersen `config.yaml`'de
`signal_mode: book_threshold` yap.)

> Bu, botun **çalışmasını** sağlar — ama hâlâ kâr garantisi **yoktur**; strateji
> beklenen değer olarak negatiftir. Demoda izle, gerçek parada dikkatli ol.

---

## 0) Gereksinimler
- **Python 3.10+** (3.11 önerilir)
- **Git**
- İnternet
- (Sadece gerçek para için) Polygon ağında **USDC** olan bir Polymarket hesabı

---

## 1) Kodu indir

İki yol var.

**A) Git ile (önerilen):**
```bash
git clone -b claude/github-repo-review-b26p51 https://github.com/altaydoganay/ton-assets.git
cd ton-assets/btc5m-bot
```

**B) ZIP olarak:** GitHub'da şu klasörü aç ve "Download ZIP" /
"Code → Download" yap:
`https://github.com/altaydoganay/ton-assets/tree/claude/github-repo-review-b26p51/btc5m-bot`

> Depo özelse, klonlarken kendi GitHub kullanıcı adın + bir Personal Access
> Token (PAT) ile giriş yapman gerekir.

---

## 2) DEMO modunda çalıştır (PARA YOK — önce bunu yap)

### Linux / macOS
```bash
cd btc5m-bot
./run.sh
```
`run.sh` otomatik olarak: sanal ortam (venv) kurar, bağımlılıkları yükler,
`config.yaml`'i örnekten oluşturur ve botu **demo** modunda başlatır.

### Windows (PowerShell — `run.sh` çalışmaz)
```powershell
cd btc5m-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
python main.py --config config.yaml
```

### Ne görmelisin
```
DEMO MODE — paper trading, no real money.
[hb] btc-updown-5m-1782312900 125s left | UP ask=0.51 DN ask=0.5 | ready | bal $1000.00 day PnL $+0.00 trades 0
ENTER UP btc-updown-5m-... @ 0.720 x6.94 ($5.00) | 118s left
EXIT  UP btc-updown-5m-... @ 0.690 (time_exit) | PnL $-0.21 | day $-0.21 | bal $999.79
```
- `[hb]` = heartbeat: bot canlı, geri sayımı ve fiyatları gösterir.
- İşlem ancak bir taraf 0.70 favori olunca açılır; olmazsa bot bekler (normal).

### Durdurma
- **Ctrl-C** → botu kapatır (state kaydedilir).
- Klasöre **`STOP`** adlı boş dosya koy → süreç çalışırken yeni işlem açmayı durdurur.
  (`touch STOP` / Windows'ta `New-Item STOP`). Silince devam eder.

Demoyu birkaç saat izle, davranışı anla. Acelen olmasın.

---

## 3) GERÇEK PARA modu (canlı)

> Buraya geçmeden önce demoyu anladığından ve riski kabul ettiğinden emin ol.

### 3.1 Polymarket hesabı ve para
1. polymarket.com'da hesap aç (e-posta veya cüzdan ile).
2. **Polygon ağında USDC** yatır. Küçük başla — örn. 10–20 USDC.
3. Polymarket'te ilk işlemde sözleşme **onayları (allowances)** otomatik istenir;
   bir kez web arayüzünden küçük bir işlem yaparak bunları onaylaman en kolayı.

### 3.2 Cüzdan modelini belirle (en kritik adım)
Polymarket'te paran genelde doğrudan cüzdanında değil, bir **proxy cüzdanda** durur:

| Hesabı nasıl açtın | `signature_type` | `FUNDER_ADDRESS` |
|---|---|---|
| Kendi cüzdanım (EOA) doğrudan USDC tutuyor | `0` | boş |
| E-posta / Magic ile açtım | `1` | proxy (hesap) adresin |
| Tarayıcı cüzdanı (MetaMask vb.) ile bağlandım | `2` | proxy (Gnosis Safe) adresin |

- **Private key:** Emirleri *imzalayan* cüzdanın özel anahtarı.
- **FUNDER_ADDRESS:** Paranın *durduğu* proxy adres (Polymarket'te hesap/
  "deposit" adresi olarak görünür). Tip 1/2 ise bunu mutlaka gir.
- Hangisi olduğundan emin değilsen: Polymarket profilinde gördüğün adres ile
  özel anahtarının adresi **farklıysa**, proxy kullanıyorsun (tip 1 veya 2).

### 3.3 Gizli bilgileri gir
```bash
cp .env.example .env
```
`.env` dosyasını düzenle:
```
PRIVATE_KEY=0xSENIN_OZEL_ANAHTARIN
FUNDER_ADDRESS=0xPROXY_ADRESIN   # tip 0 ise boş bırak
```
> `.env` git tarafından yok sayılır (gitignore'da). **Özel anahtarını asla
> kimseyle paylaşma, commit etme, ekran görüntüsüne alma.**

### 3.4 Ayarları küçük ve güvenli yap
`config.yaml` içinde:
```yaml
mode: live
signature_type: 0        # 3.2'deki tabloya göre 0 / 1 / 2
stake_usd: 1.0           # İLK kez: mümkün olan en küçük
max_notional_usd: 1.0
daily_max_loss_usd: 3.0  # günlük zarar tavanı düşük
max_trades_per_day: 3    # ilk gün az işlem
```

### 3.5 Başlat
```bash
./run.sh live
```
- `run.sh live` ayrıca `py-clob-client` (resmi SDK) kurar.
- Ekranda uyarıyı görürsün ve tam olarak şunu yazman istenir:
  **`I ACCEPT THE RISK`**
- Onay verince bot gerçek emirlerle işlem yapmaya başlar.

(Windows'ta: önce `pip install py-clob-client`, sonra
`set BOT_MODE=live` ve `python main.py --config config.yaml --i-understand-live`.)

### 3.6 İlk işlemleri yakından izle
- İlk birkaç ENTER/EXIT log'unu canlı izle; emir gerçekten doluyor mu, fiyatlar
  beklediğin gibi mi bak. Polymarket arayüzünden de pozisyonunu doğrula.
- Bir sorun görürsen **hemen `touch STOP`** ya da **Ctrl-C**.

---

## 4) Günlük kullanım / güvenlik
- **Acil durdurma:** klasörde `STOP` dosyası → yeni işlem yok. Sil → devam.
- **Günlük zarar tavanı:** `daily_max_loss_usd`'ye ulaşınca gün boyu durur.
- **State:** `state.json` bakiyeyi, günlük PnL'i, işlem sayısını saklar; yeniden
  başlatınca kaldığı yerden devam eder.
- **Loglar:** `logs/bot.log` (dönen dosya). Tüm işlemler burada.
- **7/24 çalıştırma:** Bilgisayar kapanırsa bot durur. Sürekli çalışsın istiyorsan
  bir VPS'te `screen`/`tmux` ya da `systemd` servisi içinde çalıştır.

---

## 5) Sorun giderme
- **"PRIVATE_KEY env var is required"** → `.env` doldurulmamış veya `run.sh`
  `.env`'i yüklemedi. Aynı klasörde `.env` olduğundan emin ol.
- **Bakiye 0 / emir reddi (live)** → cüzdan modeli yanlış. `signature_type` ve
  `FUNDER_ADDRESS`'i 3.2'ye göre düzelt. Allowances onaylı mı kontrol et.
- **"no market open" / sürekli bekliyor** → o an açık 5-dk round yok; bu normal,
  bot bir sonraki round'u bekler.
- **Emir doluyor ama beklenmedik fiyat** → kapanışa yakın order book ince olabilir;
  `max_entry_price`'i düşür, `stake_usd`'yi küçük tut.

---

## 6) Son hatırlatma
Negatif beklenen değer + test edilmemiş canlı yol = yüksek kayıp riski.
Bu rehber "nasıl çalıştırılır"ı anlatır; "kâr eder"i **garanti etmez** —
testlerimiz aksini gösterdi. Sorumluluk tamamen sana ait.

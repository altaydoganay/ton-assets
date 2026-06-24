# BTC 5m Polymarket — "0.70 favori" strateji backtest'i

[`Novals83/5min-btc-polymarket`](https://github.com/Novals83/5min-btc-polymarket)
botunun gerçekte çalıştırdığı stratejinin beklenen değerini (EV) ve win-rate'ini
ölçen bağımsız bir backtest iskeleti.

## Botun gerçekte yaptığı (kodundan)
1. CLOB best-ask'i izle (UP ve DOWN).
2. Bir tarafın ask'i `threshold`'u (vars. 0.70) geçince o tarafı (favoriyi) **AL**.
3. `exit_before_sec` (vars. kapanışa 20 sn) ya da stop-loss'ta **ÇIK**.
4. Settlement'a kadar **tutmaz** → PnL, son ~100 sn'deki ikincil piyasa fiyat
   değişimidir, binary $1 ödemesi değil.

README/SKILL'deki "BTC $70-100 hareket etsin / skew analizi / impulse filtresi"
anlatısı **çalışan kodda yok** (config'in kendi notu da bunu kabul ediyor).

## Model
`SyntheticDataSource` adil-kurgulu (fair-by-construction) 5 dk'lık pazarlar üretir:
- BTC, opsiyonel otokorelasyonlu (AR(1)) bir random walk izler.
- Her tarafın order-book mid'i = o tarafın paraya geçme **gerçek** olasılığı.
- ask/bid = mid ± yarı-spread + mikroyapı gürültüsü.
- Sonuç (UP/DOWN) tam patikadan belirlenir → win/loss **gerçek**, fiyattan
  türetilmez.

`--momentum 0` iken fiyat bir **martingale**'dir; strateji yalnızca maliyete
kaybedebilir. Bu, null hipotezdir. Botun tezini ("momentum devam eder") test
etmek için `--momentum RHO` ile otokorelasyon enjekte edin (>0 trend, <0
mean-reversion).

## Çalıştırma
```bash
python3 backtest_btc5m.py                 # etkin piyasa, varsayılan maliyetler
python3 backtest_btc5m.py --momentum 0.3  # trend rejimi (tezi sınar)
python3 backtest_btc5m.py --spread 0.0 --slippage-bps 0 --quote-noise 0  # maliyetsiz kontrol
python3 backtest_btc5m.py --help          # tüm bayraklar (runner'la eşleşir)
```

## Bulgular (sentetik, 20.000 pazar)
| Senaryo | Avg net EV / işlem | Win rate |
|---|---|---|
| Etkin piyasa (ρ=0) | **−3.45%** | 52% |
| Maliyetsiz + etkin | −0.70% (≈0, kalıntı stop-loss) | 59% |
| Momentum (ρ=+0.3) | **−8.18%** | 41% |
| Mean-reversion (ρ=−0.3) | +2.34% | 62% |

**Sonuçlar:**
- Etkin piyasada EV = **−maliyet** (spread+slippage), negatif. Beklendiği gibi.
- **Momentum stratejiyi KURTARMIYOR, kötüleştiriyor:** favori zaten ~1.0'a yakın
  alındığı için yukarı potansiyel kısıtlı (~0.30), ama trend ters dönünce
  stop-loss büyük kaybı realize ediyor. Asimetrik payoff momentumdan zarar görür.
- Yalnızca (gerçekçi olmayan) düşük-volatilite/mean-reverting rejimde ince bir
  artı çıkıyor.
- Stop-loss bir binary'de ekstra kayıp sızdırıyor (maliyetsiz halde bile −0.70%).
- `Final equity 0.000`: her işlemde tüm bankroll'u riske atıp 19k işlem
  compound edince ruin — agresif pozisyon boyutunun tehlikesini gösterir.

## Gerçek veriyle çalıştırmak (adaptör noktaları)
`SyntheticDataSource`'u, aynı `Market`/`Quote` arayüzünü döndüren gerçek bir
veri kaynağıyla değiştirin:

- **Polymarket CLOB geçmişi:** `data-api.polymarket.com` / Gamma API'den
  BTC up/down 5m pazarlarının token'larını ve geçmiş best bid/ask snapshot'larını
  çekin. Her pazar için saniye/poll bazında `Quote(seconds_left, up_bid, up_ask,
  dn_bid, dn_ask)` dizisi ve gerçekleşmiş `up_wins` sonucu üretin.
- **BTC spot (strike doğrulaması):** Binance/Coinbase klines ile pazarın
  açılış strike'ını ve kapanış sonucunu doğrulayın.
- Maliyetleri gerçeğe ayarlayın: `--fee-bps` (Polymarket bugün ~0), `--spread`
  ve `--slippage-bps` için defterden ölçülen gerçek değerleri kullanın.

`run_strategy`, `Params` ve metrik katmanı veri kaynağından bağımsızdır —
yalnızca veri adaptörünü yazmanız yeterli.

## Uyarı
Bu sentetik bir modeldir; mutlak sayılar model varsayımlarına bağlıdır.
**Modelden-bağımsız sağlam sonuç:** etkin (martingale) fiyat altında bu
strateji tanım gereği sıfır brüt edge'e sahiptir ve maliyet sonrası negatiftir.
Yatırım tavsiyesi değildir.

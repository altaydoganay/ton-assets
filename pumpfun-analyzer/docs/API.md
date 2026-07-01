# API Dokümantasyonu

Taban yol: `/api`. İnteraktif Swagger: `http://localhost:8000/docs`.
Tüm yanıtlar JSON'dur.

## Cüzdanlar
| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/wallets` | Cüzdan listesi (`status`, `min_score`, `limit`, `offset`) |
| GET | `/api/wallets/tracked` | Takip edilen (puan≥eşik) cüzdanlar |
| GET | `/api/wallets/{address}` | Cüzdan detayı + puan geçmişi |
| GET | `/api/wallets/{address}/score-history` | Puan geçmişi (grafik) |
| GET | `/api/wallets/{address}/relationships` | Bağlantılı cüzdanlar |
| POST | `/api/wallets/{address}/block` | Manuel engelle |
| POST | `/api/wallets/{address}/approve` | Manuel onayla/takibe al |

## Tokenler
| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/tokens` | Token listesi (`status`, `stage`, `min_score`) |
| GET | `/api/tokens/tracked` | Takip edilen tokenler |
| GET | `/api/tokens/{mint}` | Token detayı + puan geçmişi |
| GET | `/api/tokens/{mint}/score-history` | Puan geçmişi |
| GET | `/api/tokens/{mint}/holders` | Holder dağılımı (sistem/insider etiketli) |
| POST | `/api/tokens/{mint}/block` | Manuel engelle |

## Olaylar / Bildirimler / İşlemler
| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/events` | Son swap'lar (canlı olay akışı) |
| GET | `/api/alerts` | Telegram bildirimleri |
| GET | `/api/trading/paper` | Paper işlemler |
| GET | `/api/trading/live` | Canlı işlemler |
| GET | `/api/trading/positions` | Açık pozisyonlar |
| GET | `/api/trading/ai-center` | AI Decision Center: neden aldı/almadı, paper performans, exit sebepleri |
| GET | `/api/trading/decision-funnel` | Karar hunisi: blok/alım sebepleri |
| POST | `/api/trading/emergency-stop?close_positions=bool` | Acil durdurma |

## Ayarlar / Sistem
| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/settings` | Tüm ayarlar |
| GET | `/api/settings/{key}` | Tek ayar (`thresholds`, `wallet_weights`, `token_weights`, `risk`, `wallet_eligibility`) |
| PUT | `/api/settings/{key}` | Ayar güncelle (`{"value": {...}}`) |
| GET | `/api/logs` | Denetim logları (`level`, `limit`) |
| GET | `/api/health` | Servis sağlığı + aktif sağlayıcılar |

### Örnek
```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/wallets/tracked
curl -X PUT http://localhost:8000/api/settings/thresholds \
  -H 'Content-Type: application/json' \
  -d '{"value": {"wallet": 75, "token": 72}}'
```

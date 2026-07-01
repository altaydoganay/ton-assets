# BUILD 73 — PumpPortal Görünür Sağlık Logları

Bu paket BUILD 71 üstüne ek güvenlik getirir. `.env` pakete dahil değildir.

## Değişiklikler

- PumpPortal WebSocket bağlı görünse bile event akışı sessiz kalırsa otomatik reconnect yapar.
- `[AI-SCAN]` loguna `raw_age`, `new_token_age`, `trade_age`, `reconnect` alanları eklendi.
- Yeni ayar: `PUMPPORTAL_IDLE_RECONNECT_SECONDS=90` (opsiyonel).
- AI token araması 1-2 dakika sessiz kalırsa listener kendi kendini toparlar.

## Kurulum

```bat
docker compose down
docker compose up --build
```

Üst barda `BUILD 73 / UI 73` görünmeli.

"""PumpPortal canlı veri dinleyicisi.

`wss://pumpportal.fun/api/data` adresine bağlanır, takip edilen (puan ≥ eşik)
cüzdanlar için `subscribeAccountTrade` aboneliği açar ve gelen her gerçek al-sat
olayını `live_flow.handle_trade_event` ile işler.

- Takip listesi periyodik tazelenir; yeni cüzdanlar otomatik abone edilir.
- Bağlantı koparsa üssel geri çekilmeyle (max 30 sn) yeniden bağlanır.
- Canlı işlem için PumpPortal Lightning imzalayıcısı enjekte edilir (API anahtarı
  varsa). Anahtar yoksa yalnızca bildirim/paper çalışır.
"""
from __future__ import annotations

import asyncio
import json
import logging

from ..config import settings
from ..database import SessionLocal
from ..adapters.pumpportal import PumpPortalTrader, parse_trade_event
from ..models import Wallet, WalletStatus
from ..notifications.telegram import TelegramNotifier
from ..services.live_flow import handle_trade_event

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 30


def _tracked_addresses() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(Wallet.address).filter(Wallet.status == WalletStatus.tracked.value).all()
        return [r[0] for r in rows]
    finally:
        db.close()


async def run_pumpportal_listener(stop_event: asyncio.Event | None = None) -> None:
    import websockets

    signer = PumpPortalTrader() if settings.pumpportal_api_key else None
    backoff = 1.0

    while stop_event is None or not stop_event.is_set():
        subscribed: set[str] = set()
        try:
            async with websockets.connect(settings.pumpportal_data_ws, ping_interval=20) as ws:
                logger.info("PumpPortal veri akışına bağlanıldı")
                backoff = 1.0

                async def refresh_subs():
                    nonlocal subscribed
                    while stop_event is None or not stop_event.is_set():
                        current = set(_tracked_addresses())
                        new = current - subscribed
                        if new:
                            await ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": list(new)}))
                            subscribed |= new
                            logger.info("%d yeni cüzdan abone edildi (toplam %d)", len(new), len(subscribed))
                        await asyncio.sleep(REFRESH_SECONDS)

                refresher = asyncio.create_task(refresh_subs())
                try:
                    async for raw in ws:
                        if stop_event is not None and stop_event.is_set():
                            break
                        await _process(raw, signer)
                finally:
                    refresher.cancel()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PumpPortal bağlantısı koptu (%.0fs sonra tekrar): %s", backoff, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _process(raw, signer) -> None:
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    trade = parse_trade_event(msg)
    if trade is None:
        return
    db = SessionLocal()
    try:
        # Bloklayıcı DB/HTTP işlerini thread'e taşı (event loop'u kilitleme)
        await asyncio.to_thread(
            handle_trade_event, db, trade, notifier=TelegramNotifier(), signer=signer
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Olay işlenemedi: %s", exc)
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from ..security.logging_filters import install_redaction
    install_redaction()
    if not settings.live_listener_enabled:
        logger.info("Canlı dinleyici kapalı (LIVE_LISTENER_ENABLED=false)")
        return
    asyncio.run(run_pumpportal_listener())


if __name__ == "__main__":
    main()

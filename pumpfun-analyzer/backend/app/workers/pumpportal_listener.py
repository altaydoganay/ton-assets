"""PumpPortal canlı veri dinleyicisi + otomatik cüzdan keşfi.

Tek bir WebSocket bağlantısı üzerinden iki işi birlikte yapar:

  A) TAKİP: takip edilen (puan ≥ eşik) cüzdanların gerçek al-sat işlemlerine
     `subscribeAccountTrade` ile abone olur; olay gelince bildirim + (ayar
     açıksa) kopya işlem tetiklenir.

  B) KEŞİF (otomatik): `subscribeNewToken` ile yeni Pump.fun tokenlerini yakalar,
     bunların işlemlerine abone olur ve bu tokenleri ALAN cüzdanları toplar.
     Birden fazla farklı token üzerinde alım yapan cüzdanlar `discovered` olarak
     veritabanına yazılır; arka plan (Celery beat) bunları analiz edip puanlar.

Bağlantı koparsa üssel geri çekilmeyle yeniden bağlanır. Tüm bloklayıcı DB/HTTP
işleri ayrı thread'e taşınır (event loop kilitlenmez).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict

from ..config import settings
from ..database import SessionLocal
from ..adapters.pumpportal import PumpPortalTrader, parse_trade_event
from ..models import Wallet, WalletStatus
from ..notifications.telegram import TelegramNotifier
from ..services.discovery import record_candidate
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


def _is_new_token(msg: dict) -> bool:
    if msg.get("txType") in ("buy", "sell"):
        return False
    if not msg.get("mint"):
        return False
    # Yeni token olayları genelde create/isim/uri taşır.
    return msg.get("txType") == "create" or "uri" in msg or "name" in msg


class PumpPortalListener:
    def __init__(self, signer: PumpPortalTrader | None = None):
        self.signer = signer
        self.notifier = TelegramNotifier()
        self.tracked: set[str] = set()
        self.subscribed_accounts: set[str] = set()
        self.watched_tokens: "OrderedDict[str, bool]" = OrderedDict()
        self.buyer_hits: dict[str, set[str]] = {}
        self.known_candidates: set[str] = set()

    # --- abonelik bakımı ---
    async def _refresh_accounts(self, ws):
        while True:
            try:
                current = set(_tracked_addresses())
                self.tracked = current
                new = current - self.subscribed_accounts
                if new:
                    await ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": list(new)}))
                    self.subscribed_accounts |= new
                    logger.info("Takip aboneliği: +%d (toplam %d)", len(new), len(self.subscribed_accounts))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Abonelik tazeleme hatası: %s", exc)
            await asyncio.sleep(REFRESH_SECONDS)

    async def _watch_token(self, ws, mint: str):
        if mint in self.watched_tokens:
            self.watched_tokens.move_to_end(mint)
            return
        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
        self.watched_tokens[mint] = True
        # kapasite aşımında en eskiyi bırak
        while len(self.watched_tokens) > settings.discovery_max_watched_tokens:
            old, _ = self.watched_tokens.popitem(last=False)
            try:
                await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": [old]}))
            except Exception:  # noqa: BLE001
                pass

    # --- mesaj işleme ---
    async def process(self, ws, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(msg, dict):
            return

        if settings.discovery_enabled and _is_new_token(msg):
            await self._watch_token(ws, msg["mint"])
            return

        trade = parse_trade_event(msg)
        if trade is None:
            return

        if trade.trader in self.tracked:
            # Takipteki cüzdan işlemi -> bildirim + işlem akışı
            await asyncio.to_thread(self._handle_tracked, trade)
        elif settings.discovery_enabled and trade.side == "buy":
            self._record_buyer(trade.trader, trade.mint)

    def _handle_tracked(self, trade):
        db = SessionLocal()
        try:
            handle_trade_event(db, trade, notifier=self.notifier, signer=self.signer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Takip olayı işlenemedi: %s", exc)
        finally:
            db.close()

    def _record_buyer(self, trader: str, mint: str):
        if trader in self.known_candidates or trader in self.tracked:
            return
        hits = self.buyer_hits.setdefault(trader, set())
        hits.add(mint)
        if len(hits) >= settings.discovery_min_token_hits:
            self.known_candidates.add(trader)
            self.buyer_hits.pop(trader, None)
            asyncio.create_task(asyncio.to_thread(self._persist_candidate, trader))
        # bellek koruması
        if len(self.buyer_hits) > 20000:
            self.buyer_hits.clear()
        if len(self.known_candidates) > 50000:
            self.known_candidates.clear()

    def _persist_candidate(self, trader: str):
        db = SessionLocal()
        try:
            if record_candidate(db, trader, source="auto-pumpportal"):
                logger.info("Yeni aday cüzdan keşfedildi: %s", trader)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aday kaydedilemedi: %s", exc)
        finally:
            db.close()

    async def run(self, stop_event: asyncio.Event | None = None):
        import websockets

        backoff = 1.0
        while stop_event is None or not stop_event.is_set():
            self.subscribed_accounts.clear()
            self.watched_tokens.clear()
            try:
                async with websockets.connect(settings.pumpportal_data_ws, ping_interval=20) as ws:
                    logger.info("PumpPortal veri akışına bağlanıldı (keşif=%s)", settings.discovery_enabled)
                    backoff = 1.0
                    if settings.discovery_enabled:
                        await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    refresher = asyncio.create_task(self._refresh_accounts(ws))
                    try:
                        async for raw in ws:
                            if stop_event is not None and stop_event.is_set():
                                break
                            await self.process(ws, raw)
                    finally:
                        refresher.cancel()
            except Exception as exc:  # noqa: BLE001
                logger.warning("PumpPortal bağlantısı koptu (%.0fs sonra tekrar): %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


async def run_pumpportal_listener(stop_event: asyncio.Event | None = None) -> None:
    signer = PumpPortalTrader() if settings.pumpportal_api_key else None
    await PumpPortalListener(signer=signer).run(stop_event)


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

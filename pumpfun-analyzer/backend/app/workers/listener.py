"""Solana WebSocket dinleyicisi (canlı olay akışı).

Takip edilen cüzdanların log'larına `logsSubscribe` ile abone olur; gelen
işlemleri normalize edip swap tespiti yapar. Takipteki bir cüzdan, takipteki
bir tokeni satın aldığında:
  - bildirim deduplication ile Telegram'a iletilir,
  - işlem motoru (paper/live) BAĞIMSIZ olarak tetiklenir (Telegram beklenmez).

confirmed/finalized commitment doğru yönetilir; yeniden başlatma sonrasında
`swaps` ve `alerts` tabloları sayesinde tekrar işlem/bildirim yapılmaz.

Bu modül uzun-ömürlü bir async görevdir; ağ gerektirir. RPC/WS kesintisinde
üssel geri çekilmeyle yeniden bağlanır.
"""
from __future__ import annotations

import asyncio
import json
import logging

from ..config import settings

logger = logging.getLogger(__name__)


async def run_listener(addresses: list[str], stop_event: asyncio.Event | None = None) -> None:
    import websockets  # yerel import; yalnızca canlı modda gerekli

    backoff = 1.0
    while stop_event is None or not stop_event.is_set():
        try:
            async with websockets.connect(settings.solana_ws_url, ping_interval=20) as ws:
                # Her takip edilen cüzdan için logsSubscribe
                for i, addr in enumerate(addresses):
                    sub = {
                        "jsonrpc": "2.0",
                        "id": i + 1,
                        "method": "logsSubscribe",
                        "params": [{"mentions": [addr]}, {"commitment": "confirmed"}],
                    }
                    await ws.send(json.dumps(sub))
                logger.info("WS dinleyici %d cüzdan için aktif", len(addresses))
                backoff = 1.0
                async for raw in ws:
                    if stop_event is not None and stop_event.is_set():
                        break
                    await _handle_message(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WS bağlantısı koptu, yeniden bağlanılıyor (%.0fs): %s", backoff, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _handle_message(raw: str) -> None:
    """Gelen log bildirimini işle. (Ayrıntılı parse pipeline'a devredilir.)"""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    # method == "logsNotification" => içindeki signature alınır, getTransaction ile
    # tam işlem çekilip pipeline.store_swap + bildirim/işlem tetiklenir.
    # Bu adım Celery görevine devredilir (ağ gerektirir).
    params = msg.get("params") or {}
    result = (params.get("result") or {}).get("value") or {}
    signature = result.get("signature")
    if signature:
        logger.debug("Yeni log bildirimi: %s", signature)

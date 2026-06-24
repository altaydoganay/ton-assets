"""Canlı dinleyici giriş noktası.

`LISTENER_PROVIDER` ayarına göre uygun dinleyiciyi başlatır:
  - "helius"     → Helius WS (ücretsiz, SOL yakmaz; keşif + takip) [VARSAYILAN]
  - "pumpportal" → PumpPortal veri akışı (funded cüzdan, SOL ücreti)

Her iki durumda gerçek al-sat PumpPortal Lightning ile yapılır.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..security.logging_filters import install_redaction

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx/httpcore her getTransaction'ı loglar; bu spam anlamlı logları gömer.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    install_redaction()

    if not settings.live_listener_enabled:
        logger.info("Canlı dinleyici kapalı (LIVE_LISTENER_ENABLED=false)")
        return

    provider = settings.listener_provider.lower()
    if provider == "pumpportal":
        from .pumpportal_listener import run_pumpportal_listener
        logger.info("Dinleyici: PumpPortal")
        asyncio.run(run_pumpportal_listener())
    else:
        from .helius_listener import run_helius_listener
        logger.info("Dinleyici: Helius (ücretsiz, SOL yakmaz)")
        asyncio.run(run_helius_listener())


if __name__ == "__main__":
    main()

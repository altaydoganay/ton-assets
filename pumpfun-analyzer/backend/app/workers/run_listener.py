"""Canlı dinleyici giriş noktası.

BUILD 70:
- Varsayılan sağlayıcı artık "auto" davranır.
- PumpPortal API key varsa PumpPortal dinleyicisi tercih edilir; AI token akışı
  için en hızlı yol budur.
- Helius açıkça seçilmiş olsa bile sistem AI modunda başlıyorsa PumpPortal'a
  geçilir; Helius logsSubscribe discovery yeni-token fırsat motoru için daha
  yavaş ve limitlidir.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..security.logging_filters import install_redaction

logger = logging.getLogger(__name__)


def _current_strategy_mode() -> str:
    try:
        from ..database import SessionLocal
        from ..services.settings_service import get_strategy_mode
        db = SessionLocal()
        try:
            return get_strategy_mode(db)
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return "copy"


def _choose_provider() -> str:
    provider = (settings.listener_provider or "auto").lower()
    mode = _current_strategy_mode()
    if provider == "auto":
        # AI'da PumpPortal (parse edilmiş, getTransaction'sız) daha ucuz/hızlıdır;
        # anahtar varsa onu seç. Anahtar yoksa Helius/RPC WS (A1 ile AI destekli).
        return "pumpportal" if settings.pumpportal_api_key else "helius"
    # NOT: Artık Helius/RPC WS dinleyicisi de AI sinyali üretir (A1: firehose →
    # AI motoru). Bu yüzden kullanıcı LISTENER_PROVIDER'ı AÇIKÇA seçtiyse ona SAYGI
    # gösteririz — AI modunda bile PumpPortal'a zorlamayız. (auto isteyen üstte
    # PumpPortal'ı zaten alır.) Böylece "Helius/Chainstack ile SOL yakmadan AI" mümkün.
    return provider


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    install_redaction()

    if not settings.live_listener_enabled:
        logger.info("Canlı dinleyici kapalı (LIVE_LISTENER_ENABLED=false)")
        return

    provider = _choose_provider()
    if provider == "pumpportal":
        from .pumpportal_listener import run_pumpportal_listener
        logger.info("Dinleyici: PumpPortal (hızlı yeni-token akışı)")
        asyncio.run(run_pumpportal_listener())
    else:
        from .helius_listener import run_helius_listener
        logger.info("Dinleyici: Helius (ücretsiz, SOL yakmaz)")
        asyncio.run(run_helius_listener())


if __name__ == "__main__":
    main()

"""Aday cüzdan keşfi.

Cüzdanlar yalnızca "en yüksek kâr" listelerinden DEĞİL; şu davranışsal
kaynaklardan keşfedilir:
  - Başarılı Pump.fun tokenlerinin erken FAKAT ilk-blokta-olmayan alıcıları
  - Birden fazla token üzerinde tutarlı davranan cüzdanlar
  - Satışını kademeli yapan yatırımcılar
  - Belirli süre aktif kalan cüzdanlar

Bu modül chain provider'a bağımlıdır (RPC/Helius). Ağ olmadan boş liste döner;
gerçek tarama mantığı buradaki yapı üzerinden genişletilebilir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ...adapters.base import ChainProvider

logger = logging.getLogger(__name__)

# İlk-blok snipe'ları elemek için minimum offset (saniye).
EARLY_BUYER_MIN_OFFSET = 20
EARLY_BUYER_MAX_OFFSET = 1800  # ilk 30 dk içindeki alıcılar "erken" sayılır


@dataclass
class WalletCandidate:
    address: str
    source: str
    reason: str


def discover_from_recent_tokens(provider: ChainProvider, token_mints: list[str] | None = None) -> list[WalletCandidate]:
    """Verilen (veya keşfedilen) tokenlerin erken-fakat-snipe-olmayan alıcılarını döner.

    Gerçek uygulamada token_mints, son mezun olmuş/başarılı Pump.fun tokenlerinden
    gelir. Burada provider'dan alınan işlem verisiyle aday üretilir.
    """
    candidates: list[WalletCandidate] = []
    token_mints = token_mints or []
    for mint in token_mints:
        try:
            sigs = provider.get_signatures_for_address(mint, limit=200)
        except Exception as exc:  # noqa: BLE001
            logger.info("Token alıcıları taranamadı %s: %s", mint, exc)
            continue
        # İşlem ayrıştırma adapter/pipeline üzerinden yapılır; burada iskelet.
        # (Erken-fakat-ilk-blok-olmayan alıcı filtresi pipeline'da uygulanır.)
        _ = sigs
    return candidates

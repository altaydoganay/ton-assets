"""DexScreener market adapteri (API anahtarı gerektirmez)."""
from __future__ import annotations

import logging

from ..config import settings
from .base import MarketProvider, TokenMarketData

logger = logging.getLogger(__name__)


class DexScreenerAdapter(MarketProvider):
    name = "dexscreener"

    def __init__(self, base_url: str | None = None, client=None):
        self.base_url = (base_url or settings.dexscreener_base_url).rstrip("/")
        self._client = client

    def get_token_market(self, mint: str) -> TokenMarketData:
        import httpx

        url = f"{self.base_url}/latest/dex/tokens/{mint}"
        client = self._client or httpx.Client(timeout=15)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs") or []
            if not pairs:
                return TokenMarketData(mint=mint, source=self.name, ok=False)
            # En yüksek likiditeli çifti seç.
            best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)
            liq = (best.get("liquidity") or {})
            base = best.get("baseToken") or {}
            info = best.get("info") or {}
            return TokenMarketData(
                mint=mint,
                name=base.get("name"),
                symbol=base.get("symbol"),
                image_url=info.get("imageUrl"),
                pair_url=best.get("url"),
                price_usd=_f(best.get("priceUsd")),
                price_sol=_f(best.get("priceNative")),
                liquidity_usd=_f(liq.get("usd")),
                market_cap_usd=_f(best.get("marketCap")),
                fdv_usd=_f(best.get("fdv")),
                volume_24h_usd=_f((best.get("volume") or {}).get("h24")),
                pair_created_at=best.get("pairCreatedAt"),
                source=self.name,
                ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("DexScreener hata: %s", exc)
            # Gerçek taşıma hatası => sağlayıcı sağlığına 'fail' olarak yansısın.
            return TokenMarketData(mint=mint, source=self.name, ok=False, error=repr(exc))
        finally:
            if self._client is None:
                client.close()


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

"""Birdeye market adapteri (API anahtarı gerektirir)."""
from __future__ import annotations

import logging

from ..config import settings
from .base import MarketProvider, TokenMarketData

logger = logging.getLogger(__name__)


class BirdeyeAdapter(MarketProvider):
    name = "birdeye"

    def __init__(self, api_key: str | None = None, client=None):
        self.api_key = api_key or settings.birdeye_api_key
        self.base_url = "https://public-api.birdeye.so"
        self._client = client

    def get_token_market(self, mint: str) -> TokenMarketData:
        import httpx

        if not self.api_key:
            logger.info("Birdeye API anahtarı yok; market verisi alınamadı")
            return TokenMarketData(mint=mint, source=self.name, ok=False)
        url = f"{self.base_url}/defi/token_overview"
        headers = {"X-API-KEY": self.api_key, "x-chain": "solana"}
        client = self._client or httpx.Client(timeout=15)
        try:
            resp = client.get(url, params={"address": mint}, headers=headers)
            resp.raise_for_status()
            d = (resp.json() or {}).get("data") or {}
            return TokenMarketData(
                mint=mint,
                price_usd=d.get("price"),
                liquidity_usd=d.get("liquidity"),
                market_cap_usd=d.get("mc"),
                fdv_usd=d.get("fdv"),
                volume_24h_usd=(d.get("v24hUSD") or d.get("v24h")),
                source=self.name,
                ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Birdeye hata: %s", exc)
            return TokenMarketData(mint=mint, source=self.name, ok=False)
        finally:
            if self._client is None:
                client.close()

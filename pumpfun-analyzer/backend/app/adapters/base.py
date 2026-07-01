"""Veri sağlayıcı adapter arayüzleri.

Sağlayıcılar (Helius, standart RPC, Birdeye, DexScreener) ortak arayüzler
arkasında soyutlanır; böylece ayarlardan (chain_provider / market_provider)
değiştirilebilir ve test edilebilir.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class TokenMarketData:
    mint: str
    name: str | None = None
    symbol: str | None = None
    image_url: str | None = None
    pair_url: str | None = None
    price_usd: float | None = None
    price_sol: float | None = None
    liquidity_usd: float | None = None
    liquidity_sol: float | None = None
    market_cap_usd: float | None = None
    fdv_usd: float | None = None
    volume_24h_usd: float | None = None
    pair_created_at: int | None = None
    source: str = ""
    ok: bool = False


class ChainProvider(ABC):
    """Zincir üstü veri (işlemler, hesaplar, mint bilgisi)."""

    name: str = "chain"

    @abstractmethod
    def get_signatures_for_address(self, address: str, limit: int = 100) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_transaction(self, signature: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def get_token_supply(self, mint: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def get_mint_info(self, mint: str) -> dict[str, Any] | None:
        """mint/freeze authority gibi güvenlik bilgisi."""
        ...


class MarketProvider(ABC):
    """Fiyat / likidite / hacim verisi."""

    name: str = "market"

    @abstractmethod
    def get_token_market(self, mint: str) -> TokenMarketData:
        ...


class RpcTransport(Protocol):
    """JSON-RPC POST taşıyıcısı (test'te mock'lanabilir)."""

    def post(self, url: str, json: dict[str, Any]) -> dict[str, Any]:
        ...

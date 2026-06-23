"""Adapter seçimi (ayarlardan).

`chain_provider` ve `market_provider` ayarlarına göre uygun adapter örneğini
üretir. Bu sayede sağlayıcılar koda dokunmadan değiştirilebilir.
"""
from __future__ import annotations

from ..config import settings
from .base import ChainProvider, MarketProvider
from .birdeye import BirdeyeAdapter
from .dexscreener import DexScreenerAdapter
from .helius import HeliusAdapter
from .rpc import SolanaRpcAdapter


def build_chain_provider(throttle: bool = True) -> ChainProvider:
    """Zincir sağlayıcı. `throttle=False` (canlı alım yolu) hız limiti beklemesi
    uygulamaz — düşük gecikme için. Arka plan keşfinde `throttle=True` kalır."""
    provider = settings.chain_provider.lower()
    mi = settings.rpc_min_interval_seconds if throttle else 0.0
    rr = settings.rpc_rate_limit_retries
    if provider == "helius" and settings.helius_api_key:
        return HeliusAdapter(
            api_key=settings.helius_api_key, rpc_url=settings.helius_rpc_url or None,
            min_interval=mi, rate_limit_retries=rr,
        )
    # Varsayılan: standart RPC (gerekirse Helius RPC'yi de failover olarak ekle)
    endpoints = [settings.solana_rpc_url]
    if settings.helius_rpc_url:
        endpoints.append(settings.helius_rpc_url)
    return SolanaRpcAdapter(endpoints=endpoints, min_interval=mi, rate_limit_retries=rr)


def build_market_provider() -> MarketProvider:
    provider = settings.market_provider.lower()
    if provider == "birdeye" and settings.birdeye_api_key:
        return BirdeyeAdapter()
    return DexScreenerAdapter()

"""Adapter seçimi (ayarlardan).

`chain_provider` ve `market_provider` ayarlarına göre uygun adapter örneğini
üretir. Bu sayede sağlayıcılar koda dokunmadan değiştirilebilir.
"""
from __future__ import annotations

from ..config import settings
from .base import ChainProvider, MarketProvider
from .birdeye import BirdeyeAdapter
from .dexscreener import DexScreenerAdapter
from .health_tracking import HealthTrackingChainProvider, HealthTrackingMarketProvider
from .helius import HeliusAdapter
from .rpc import SolanaRpcAdapter


def build_chain_provider(throttle: bool = True) -> ChainProvider:
    """Zincir sağlayıcı. `throttle=False` (canlı alım yolu) hız limiti beklemesi
    uygulamaz — düşük gecikme için. Arka plan keşfinde `throttle=True` kalır.

    Dönen sağlayıcı sağlık-takipli sarmalayıcı ile sarılır (davranış aynı, her
    çağrı `provider_health`'e kaydedilir)."""
    mi = settings.rpc_min_interval_seconds if throttle else 0.0
    rr = settings.rpc_rate_limit_retries
    # HELIUS_API_KEY tanımlıysa DAİMA Helius kullan — Enhanced Transactions
    # (cüzdan başına tek istek) hem ~10× daha ucuz hem de daha derindir. Eski
    # .env'de CHAIN_PROVIDER=rpc kalmış olsa bile bu ayar tuzağına düşmeyiz;
    # anahtar = niyet. (Anahtar YOKSA otomatik standart RPC'ye düşülür.)
    if settings.helius_api_key:
        inner: ChainProvider = HeliusAdapter(
            api_key=settings.helius_api_key, rpc_url=settings.helius_rpc_url or None,
            min_interval=mi, rate_limit_retries=rr,
        )
        return HealthTrackingChainProvider(inner)
    # Varsayılan: standart RPC (gerekirse Helius RPC'yi de failover olarak ekle)
    endpoints = [settings.solana_rpc_url]
    # Yedek RPC: birincil (örn. Chainstack free) getSignaturesForAddress'i plan
    # limitiyle reddederse o metod buraya METOD-BAZLI düşer. Public RPC izin verir.
    fb = settings.solana_rpc_fallback_url
    if fb and fb not in endpoints:
        endpoints.append(fb)
    if settings.helius_rpc_url:
        # Anahtar yokken bile URL'de gömülü anahtar güncel HELIUS_API_KEY'e hizalanır
        from .helius import with_api_key
        endpoints.append(with_api_key(settings.helius_rpc_url, settings.helius_api_key)
                         if settings.helius_api_key else settings.helius_rpc_url)
    return HealthTrackingChainProvider(
        SolanaRpcAdapter(endpoints=endpoints, min_interval=mi, rate_limit_retries=rr)
    )


def build_market_provider() -> MarketProvider:
    provider = settings.market_provider.lower()
    if provider == "birdeye" and settings.birdeye_api_key:
        return HealthTrackingMarketProvider(BirdeyeAdapter())
    return HealthTrackingMarketProvider(DexScreenerAdapter())

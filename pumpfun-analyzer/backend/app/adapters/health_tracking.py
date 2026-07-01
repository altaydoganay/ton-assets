"""Sağlık-takipli sağlayıcı sarmalayıcıları (decorator).

Gerçek adapter'ı sarar; her çağrının süresini ve sonucunu `provider_health`
kaydına yazar. Asıl davranışı DEĞİŞTİRMEZ — sonuç/exception aynen geçer, sadece
gözlemlenir. Böylece kayıt mantığını her adapter'a serpiştirmeye gerek kalmaz.
"""
from __future__ import annotations

import time
from typing import Any

from ..services import provider_health
from .base import ChainProvider, MarketProvider, TokenMarketData


class HealthTrackingMarketProvider(MarketProvider):
    def __init__(self, inner: MarketProvider):
        self._inner = inner
        self.name = getattr(inner, "name", "market")

    def get_token_market(self, mint: str) -> TokenMarketData:
        t0 = time.time()
        try:
            data = self._inner.get_token_market(mint)
        except Exception as exc:  # noqa: BLE001
            provider_health.record(self.name, "market", ok=False,
                                   latency_ms=(time.time() - t0) * 1000, error=repr(exc))
            raise
        # SAĞLAYICI SAĞLIĞI, VERİ-YOK'tan ayrılır: gerçek taşıma hatası (data.error
        # dolu) => fail. Taze token için "çift bulunamadı" (ok=False, error=None)
        # sağlayıcının SAĞLIKLI yanıtıdır => ok. Aksi halde her fresh pump.fun
        # token'i sağlayıcıyı yanlışlıkla 'down' gösterirdi.
        err = getattr(data, "error", None)
        healthy = err is None
        provider_health.record(self.name, "market", ok=healthy,
                               latency_ms=(time.time() - t0) * 1000, error=err)
        return data


class HealthTrackingChainProvider(ChainProvider):
    def __init__(self, inner: ChainProvider):
        self._inner = inner
        self.name = getattr(inner, "name", "chain")

    def _timed(self, method: str, *args: Any, **kwargs: Any) -> Any:
        t0 = time.time()
        try:
            res = getattr(self._inner, method)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            provider_health.record(self.name, "chain", ok=False,
                                   latency_ms=(time.time() - t0) * 1000, error=repr(exc))
            raise
        # Zincir çağrısında None dönüş MEŞRU olabilir (örn. bulunamayan işlem);
        # exception atmadıysa çağrı başarılıdır.
        provider_health.record(self.name, "chain", ok=True,
                               latency_ms=(time.time() - t0) * 1000)
        return res

    def get_signatures_for_address(self, address: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._timed("get_signatures_for_address", address, limit=limit)

    def get_transaction(self, signature: str) -> dict[str, Any] | None:
        return self._timed("get_transaction", signature)

    def get_token_supply(self, mint: str) -> dict[str, Any] | None:
        return self._timed("get_token_supply", mint)

    def get_mint_info(self, mint: str) -> dict[str, Any] | None:
        return self._timed("get_mint_info", mint)

    def get_token_largest_accounts(self, mint: str) -> Any:
        # Bazı adapter'larda ek metot; varsa geçir, yoksa AttributeError doğal.
        return self._timed("get_token_largest_accounts", mint)

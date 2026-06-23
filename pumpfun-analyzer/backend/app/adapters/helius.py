"""Helius adapteri.

Helius, geliştirilmiş RPC + zenginleştirilmiş işlem (enhanced transactions)
sunar. Standart RPC çağrıları için `SolanaRpcAdapter` davranışını miras alır;
ek olarak enhanced transactions endpoint'ini kullanabilir.
"""
from __future__ import annotations

from typing import Any

from .rpc import SolanaRpcAdapter, Transport


class HeliusAdapter(SolanaRpcAdapter):
    name = "helius"

    def __init__(self, api_key: str, rpc_url: str | None = None, transport: Transport | None = None,
                 min_interval: float = 0.0, rate_limit_retries: int = 6):
        self.api_key = api_key
        url = rpc_url or f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        super().__init__(endpoints=[url], transport=transport,
                         min_interval=min_interval, rate_limit_retries=rate_limit_retries)
        self._enhanced_base = "https://api.helius.xyz/v0"

    def get_enhanced_transactions(self, signatures: list[str]) -> list[dict[str, Any]]:
        """Enhanced transactions (parse edilmiş swap/transfer bilgisi)."""
        import httpx

        url = f"{self._enhanced_base}/transactions?api-key={self.api_key}"
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, json={"transactions": signatures})
            resp.raise_for_status()
            return resp.json()

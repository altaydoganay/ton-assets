"""Solana JSON-RPC adapteri (failover destekli).

Birden çok RPC endpoint'i sırayla denenir; biri hata verirse (ağ hatası,
HTTP 5xx, RPC error) sonrakine geçilir. Tüm endpoint'ler başarısız olursa
`RpcUnavailableError` yükseltilir. Bu sayede RPC kesintisi sağlam yönetilir.

Taşıyıcı (transport) enjekte edilebilir; testte mock ile failover doğrulanır.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .base import ChainProvider

logger = logging.getLogger(__name__)


class RpcUnavailableError(RuntimeError):
    pass


class RpcError(RuntimeError):
    pass


# transport: (url, payload) -> response dict
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


def _httpx_transport(timeout: float = 15.0) -> Transport:
    import httpx

    def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code >= 500:
                raise RpcError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()

    return _post


class SolanaRpcAdapter(ChainProvider):
    name = "rpc"

    def __init__(self, endpoints: list[str], transport: Transport | None = None, max_attempts_per_endpoint: int = 1):
        if not endpoints:
            raise ValueError("En az bir RPC endpoint gerekli")
        self.endpoints = endpoints
        self.transport = transport or _httpx_transport()
        self.max_attempts_per_endpoint = max_attempts_per_endpoint
        self._healthy: dict[str, bool] = {e: True for e in endpoints}

    def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_err: Exception | None = None
        # Sağlıklı endpoint'leri önce dene.
        ordered = sorted(self.endpoints, key=lambda e: not self._healthy.get(e, True))
        for url in ordered:
            for _ in range(self.max_attempts_per_endpoint):
                try:
                    data = self.transport(url, payload)
                    if isinstance(data, dict) and data.get("error"):
                        raise RpcError(str(data["error"]))
                    self._healthy[url] = True
                    return data.get("result") if isinstance(data, dict) else data
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    self._healthy[url] = False
                    logger.warning("RPC endpoint hata verdi, sonrakine geçiliyor: %s (%s)", url, exc)
                    break  # bu endpoint'i bırak, sonrakine geç
        raise RpcUnavailableError(f"Tüm RPC endpoint'leri başarısız: {last_err}")

    # --- ChainProvider arayüzü ---
    def get_signatures_for_address(self, address: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._rpc("getSignaturesForAddress", [address, {"limit": limit}]) or []

    def get_transaction(self, signature: str) -> dict[str, Any] | None:
        return self._rpc(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}],
        )

    def get_token_supply(self, mint: str) -> dict[str, Any] | None:
        return self._rpc("getTokenSupply", [mint])

    def get_mint_info(self, mint: str) -> dict[str, Any] | None:
        res = self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        try:
            return res["value"]["data"]["parsed"]["info"]
        except (TypeError, KeyError):
            return None

    def get_latest_blockhash(self) -> dict[str, Any] | None:
        return self._rpc("getLatestBlockhash", [{"commitment": "finalized"}])

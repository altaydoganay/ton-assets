"""Solana JSON-RPC adapteri (failover destekli).

Birden çok RPC endpoint'i sırayla denenir; biri hata verirse (ağ hatası,
HTTP 5xx, RPC error) sonrakine geçilir. Tüm endpoint'ler başarısız olursa
`RpcUnavailableError` yükseltilir. Bu sayede RPC kesintisi sağlam yönetilir.

Taşıyıcı (transport) enjekte edilebilir; testte mock ile failover doğrulanır.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .base import ChainProvider

logger = logging.getLogger(__name__)


class RpcUnavailableError(RuntimeError):
    pass


class RpcError(RuntimeError):
    pass


class RateLimitError(RuntimeError):
    """HTTP 429 — hız limiti. Aynı endpoint'te bekleyip yeniden denenir."""
    pass


# transport: (url, payload) -> response dict
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]

TOKEN_PROGRAM_IDS = [
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token
    "TokenzQdBNbLqP5VEhdkAS6EPF7uAwBCoNtH9Q2ZcS",   # Token-2022
]


def _httpx_transport(timeout: float = 15.0) -> Transport:
    import httpx

    def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 429:
                raise RateLimitError("HTTP 429")
            if resp.status_code >= 500:
                raise RpcError(f"HTTP {resp.status_code}")
            # 403 vb. gövdesinde JSON-RPC error taşıyabilir (örn. Chainstack arşiv
            # plan limiti: kod -32002). Bunu üst katmana JSON olarak bırakırız ki
            # METOD-BAZLI ele alınabilsin (endpoint'i tümden sağlıksız saymadan).
            try:
                return resp.json()
            except Exception:  # noqa: BLE001 — JSON değilse gerçek transport hatası
                resp.raise_for_status()
                raise RpcError(f"HTTP {resp.status_code} non-JSON")

    return _post


def _is_plan_limited(err: Any) -> bool:
    """Endpoint bu METODU desteklemiyor (plan limiti / arşiv / method-not-found)?
    Bu durumda endpoint SAĞLIKSIZ sayılmaz; yalnız o metod için yedeğe düşülür.

    Chainstack free örnekleri:
      -32002 'Archive, Debug and Trace ... not available on your current plan'
      -32602 'Method requires plan upgrade. See ...chainstack.com/docs/limits'  (getTokenAccountsByOwner)
      -32601 'Method not found'  (getAssetsByOwner / DAS — bu node'da yok)
    """
    if not isinstance(err, dict):
        return False
    if err.get("code") == -32002:
        return True
    msg = str(err.get("message") or "").lower()
    keys = ("current plan", "plan upgrade", "requires plan", "requires a paid",
            "archive", "not available on your", "chainstack.com/docs/limits", "method not found")
    return any(k in msg for k in keys)


class SolanaRpcAdapter(ChainProvider):
    name = "rpc"

    def __init__(
        self,
        endpoints: list[str],
        transport: Transport | None = None,
        max_attempts_per_endpoint: int = 1,
        min_interval: float = 0.0,
        rate_limit_retries: int = 5,
    ):
        if not endpoints:
            raise ValueError("En az bir RPC endpoint gerekli")
        self.endpoints = endpoints
        self.transport = transport or _httpx_transport()
        self.max_attempts_per_endpoint = max_attempts_per_endpoint
        # İstekler arası asgari süre (saniye) — sağlayıcı hız limitini korur.
        self.min_interval = min_interval
        # 429 alındığında aynı endpoint'te kaç kez beklenip tekrar denensin.
        self.rate_limit_retries = rate_limit_retries
        self._last_request = 0.0
        self._healthy: dict[str, bool] = {e: True for e in endpoints}
        # (method -> bu metodu plan/arşiv limitiyle reddeden endpoint'ler). Bu
        # endpoint'ler O METOD için atlanır ama diğer metodlarda kullanılmaya devam.
        self._method_blocked: dict[str, set[str]] = {}

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_err: Exception | None = None
        # Bu metodu plan limitiyle reddeden endpoint'leri ELE; sağlıklıyı öne al.
        blocked = self._method_blocked.get(method, set())
        usable = [e for e in self.endpoints if e not in blocked] or list(self.endpoints)
        ordered = sorted(usable, key=lambda e: not self._healthy.get(e, True))
        for url in ordered:
            rl_attempts = 0
            while True:
                self._throttle()
                try:
                    data = self.transport(url, payload)
                    if isinstance(data, dict) and data.get("error"):
                        err = data["error"]
                        # PLAN/ARŞİV limiti: endpoint sağlıklı ama bu metodu vermiyor
                        # → metod-bazlı engelle, endpoint'i SAĞLIKSIZ SAYMA, sonrakine geç.
                        if _is_plan_limited(err):
                            self._method_blocked.setdefault(method, set()).add(url)
                            last_err = RpcError(str(err))
                            logger.warning("Endpoint '%s' metodu plan limitiyle reddetti (%s); "
                                           "bu metod yedek endpoint'e yönlendiriliyor", url, method)
                            break  # sonraki endpoint
                        raise RpcError(str(err))
                    self._healthy[url] = True
                    return data.get("result") if isinstance(data, dict) else data
                except RateLimitError as exc:
                    # Hız limiti: endpoint'i ölü sayma; bekle ve aynı endpoint'te
                    # yeniden dene (üssel geri çekilme).
                    last_err = exc
                    rl_attempts += 1
                    if rl_attempts > self.rate_limit_retries:
                        logger.warning("429 limiti aşıldı, sonraki endpoint'e geçiliyor: %s", url)
                        break
                    backoff = min(0.5 * (2 ** (rl_attempts - 1)), 8.0)
                    time.sleep(backoff)
                    continue
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
        # commitment="confirmed": logsSubscribe "confirmed"de tetiklenir; finalized
        # beklenirse işlem henüz bulunamayıp None döner ve keşif boşa çıkar.
        return self._rpc(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed",
                         "commitment": "confirmed"}],
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

    def get_balance_sol(self, address: str, commitment: str = "confirmed") -> float:
        res = self._rpc("getBalance", [address, {"commitment": commitment}])
        try:
            return float(res.get("value") or 0) / 1_000_000_000
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def get_token_accounts_by_owner(self, owner: str, commitment: str = "confirmed") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for program_id in TOKEN_PROGRAM_IDS:
            try:
                res = self._rpc(
                    "getTokenAccountsByOwner",
                    [
                        owner,
                        {"programId": program_id},
                        {"encoding": "jsonParsed", "commitment": commitment},
                    ],
                )
                rows = list(res.get("value") or []) if isinstance(res, dict) else []
            except Exception as exc:  # noqa: BLE001
                logger.warning("Token account okunamadı (%s): %s", program_id, exc)
                rows = []
            for row in rows:
                pubkey = str(row.get("pubkey") or "")
                if pubkey and pubkey in seen:
                    continue
                if pubkey:
                    seen.add(pubkey)
                row["program_id"] = program_id
                out.append(row)
        return out

    def get_assets_by_owner(self, owner: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Helius DAS uyumlu endpoint. Standart RPC'de desteklenmeyebilir."""
        res = self._rpc(
            "getAssetsByOwner",
            [{
                "ownerAddress": owner,
                "page": 1,
                "limit": max(1, min(int(limit), 1000)),
                "displayOptions": {
                    "showFungible": True,
                    "showNativeBalance": False,
                    "showCollectionMetadata": False,
                },
            }],
        )
        try:
            return list(res.get("items") or [])
        except AttributeError:
            return []

    def get_token_largest_accounts(self, mint: str) -> list[dict[str, Any]]:
        res = self._rpc("getTokenLargestAccounts", [mint])
        try:
            return res["value"] or []
        except (TypeError, KeyError):
            return []

"""PumpPortal adapteri — canlı veri akışı + işlem gönderimi.

İki yetenek:
  1) Veri akışı (ücretsiz, anahtarsız): `wss://pumpportal.fun/api/data` üzerinden
     `subscribeAccountTrade` ile takip edilen cüzdanların GERÇEK al-sat işlemleri
     anlık olarak alınır. Transferler bu akışta yer almaz (yalnızca swap'lar).
  2) İşlem gönderimi (Lightning API, anahtar gerektirir): PumpPortal kendi
     tarafındaki cüzdanla işlemi imzalayıp zincire gönderir; böylece özel anahtar
     bizim sistemimize hiç girmez. API anahtarı GİZLİ kabul edilir, loglanmaz.

PumpPortal trade event şeması (özet): txType ("buy"/"sell"), traderPublicKey,
mint, solAmount, tokenAmount, signature, marketCapSol, pool, ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class PumpPortalTrade:
    signature: str
    trader: str
    mint: str
    side: str            # "buy" | "sell"
    sol_amount: float
    token_amount: float
    pool: str | None
    market_cap_sol: float | None
    raw: dict


def parse_trade_event(msg: dict) -> PumpPortalTrade | None:
    """PumpPortal WS trade mesajını normalleştirir. Trade değilse None."""
    tx_type = (msg.get("txType") or msg.get("type") or "").lower()
    if tx_type not in ("buy", "sell"):
        return None
    trader = msg.get("traderPublicKey") or msg.get("trader")
    mint = msg.get("mint")
    if not trader or not mint:
        return None
    return PumpPortalTrade(
        signature=msg.get("signature") or "",
        trader=trader,
        mint=mint,
        side=tx_type,
        sol_amount=float(msg.get("solAmount") or 0.0),
        token_amount=float(msg.get("tokenAmount") or 0.0),
        pool=msg.get("pool"),
        market_cap_sol=_f(msg.get("marketCapSol")),
        raw=msg,
    )


class PumpPortalTradeError(RuntimeError):
    pass


class PumpPortalTrader:
    """Lightning işlem API'si üzerinden gerçek al-sat. `signer` arayüzünü uygular."""

    def __init__(self, api_key: str | None = None, trade_url: str | None = None,
                 pool: str | None = None, client=None):
        self.api_key = api_key or settings.pumpportal_api_key
        self.trade_url = trade_url or settings.pumpportal_trade_url
        self.pool = pool or settings.pumpportal_default_pool
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _trade(self, body: dict) -> str:
        import httpx

        if not self.api_key:
            raise PumpPortalTradeError("PumpPortal API anahtarı tanımlı değil")
        client = self._client or httpx.Client(timeout=20)
        try:
            resp = client.post(self.trade_url, params={"api-key": self.api_key}, json=body)
            if resp.status_code != 200:
                # Yanıt gövdesini loglarken anahtar zaten URL param; gövde güvenli.
                raise PumpPortalTradeError(f"HTTP {resp.status_code}: {resp.text[:160]}")
            data = resp.json()
            sig = data.get("signature") or data.get("txid")
            if not sig:
                raise PumpPortalTradeError(f"İmza dönmedi: {str(data)[:160]}")
            return sig
        finally:
            if self._client is None:
                client.close()

    # --- signer arayüzü (CopyTradeEngine tarafından çağrılır) ---
    def submit_buy(self, token_mint: str, sol_amount: float, market_price_sol: float,
                   max_slippage: float = 0.15, priority_fee_sol: float = 0.0005) -> str:
        body = {
            "action": "buy",
            "mint": token_mint,
            "amount": sol_amount,
            "denominatedInSol": "true",
            "slippage": int(max_slippage * 100),
            "priorityFee": priority_fee_sol,
            "pool": self.pool,
        }
        return self._trade(body)

    def submit_sell(self, token_mint: str, fraction: float, market_price_sol: float,
                    max_slippage: float = 0.15, priority_fee_sol: float = 0.0005) -> str:
        # PumpPortal satışta yüzde kabul eder ("50%").
        pct = max(1, min(100, round(fraction * 100)))
        body = {
            "action": "sell",
            "mint": token_mint,
            "amount": f"{pct}%",
            "denominatedInSol": "false",
            "slippage": int(max_slippage * 100),
            "priorityFee": priority_fee_sol,
            "pool": self.pool,
        }
        return self._trade(body)


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

"""Broker abstraction: PaperBroker (demo) and PolymarketBroker (real money).

The engine only ever calls buy()/sell(); the mode decides which broker is used.
The live broker talks to Polymarket via the official py-clob-client and is gated
behind explicit confirmation in main.py.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

from .config import Config


@dataclass
class Fill:
    token: str
    side: str            # "BUY" | "SELL"
    price: float         # average fill price
    shares: float
    ok: bool
    info: str = ""


class Broker:
    def buy(self, token: str, price: float, shares: float) -> Fill: ...
    def sell(self, token: str, price: float, shares: float) -> Fill: ...
    def name(self) -> str: ...


# --------------------------------------------------------------------------- #
# DEMO — paper trading. No money moves. Fills are simulated at the quoted
# price with a configurable slippage, exactly like the backtest cost model.
# --------------------------------------------------------------------------- #
class PaperBroker(Broker):
    def __init__(self, cfg: Config):
        self.slip = cfg.slippage_bps / 1e4

    def name(self) -> str:
        return "PAPER (demo)"

    def buy(self, token, price, shares) -> Fill:
        fill_px = price * (1.0 + self.slip)      # pay up a touch
        return Fill(token, "BUY", fill_px, shares, True, "simulated")

    def sell(self, token, price, shares) -> Fill:
        fill_px = price * (1.0 - self.slip)      # receive a touch less
        return Fill(token, "SELL", fill_px, shares, True, "simulated")


# --------------------------------------------------------------------------- #
# LIVE — real money on Polymarket. Requires PRIVATE_KEY (Polygon wallet with
# USDC + allowances set). Implemented against py-clob-client; marked UNTESTED
# with real funds — verify with a tiny stake before trusting it.
# --------------------------------------------------------------------------- #
class PolymarketBroker(Broker):
    def __init__(self, cfg: Config):
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        pk = os.environ.get("PRIVATE_KEY")
        if not pk:
            raise RuntimeError("PRIVATE_KEY env var is required for live mode")
        funder = os.environ.get("FUNDER_ADDRESS")  # proxy wallet for sig_type 1/2

        self.cfg = cfg
        kwargs = dict(key=pk, chain_id=cfg.chain_id,
                      signature_type=cfg.signature_type)
        if funder:
            kwargs["funder"] = funder
        self.client = ClobClient(cfg.clob_host, **kwargs)
        # derive/attach L2 API credentials for order signing
        creds = self.client.create_or_derive_api_creds()
        self.client.set_api_creds(creds)

    def name(self) -> str:
        return "POLYMARKET (LIVE — real money)"

    def _send(self, token, price, shares, side) -> Fill:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL
        s = BUY if side == "BUY" else SELL
        # marketable limit: cross at the quoted price, fill-or-kill so we never
        # leave a resting order we won't manage.
        args = OrderArgs(price=round(float(price), 3), size=round(float(shares), 2),
                         side=s, token_id=token)
        try:
            signed = self.client.create_order(args)
            resp = self.client.post_order(signed, OrderType.FOK)
            ok = bool(resp and resp.get("success", False))
            return Fill(token, side, float(price), float(shares), ok, str(resp))
        except Exception as e:
            return Fill(token, side, float(price), float(shares), False, f"error: {e}")

    def buy(self, token, price, shares) -> Fill:
        return self._send(token, price, shares, "BUY")

    def sell(self, token, price, shares) -> Fill:
        return self._send(token, price, shares, "SELL")


def make_broker(cfg: Config) -> Broker:
    if cfg.mode == "live":
        return PolymarketBroker(cfg)
    return PaperBroker(cfg)

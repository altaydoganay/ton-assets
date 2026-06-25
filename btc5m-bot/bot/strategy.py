"""Strategy logic for the btc-updown-5m markets.

Two entry modes:

  btc_move (default) — use the REAL signal that is actually available in time:
      the live BTC move vs the window's strike. On these markets the order book
      stays ~0.50 until the final seconds, so waiting for a 0.70 ask almost never
      fires in calm conditions. BTC-vs-strike, by contrast, is observable every
      tick. Enter the favored side once |spot - strike| >= move_threshold_usd.

  book_threshold — the original bot's logic: buy a side whose ask is already in
      [threshold, max_entry_price]. Kept for reference/comparison.

Exit (both): stop-loss (mark <= entry*(1-stop_loss_pct)) OR seconds_left <= exit_before_sec.
"""
from __future__ import annotations
from dataclasses import dataclass

from .market import Quote
from .config import Config


@dataclass
class EntrySignal:
    side: str            # "UP" | "DOWN"
    token: str
    ask: float


def entry_signal_btc_move(q: Quote, cfg: Config, strike: float | None,
                          spot: float | None) -> EntrySignal | None:
    if strike is None or spot is None:
        return None
    if not (cfg.min_entry_seconds_left <= q.seconds_left <= cfg.entry_window_max_sec):
        return None
    move = spot - strike
    if abs(move) < cfg.move_threshold_usd:
        return None
    if move > 0:
        side, token, bid, ask = "UP", q.up_token, q.up_bid, q.up_ask
    else:
        side, token, bid, ask = "DOWN", q.dn_token, q.dn_bid, q.dn_ask
    if ask is None or ask > cfg.max_entry_price:
        return None
    # book-agreement guard: don't buy a side the book strongly disfavors
    # (protects against strike-proxy error or an already-reversed move)
    if bid is not None:
        if (bid + ask) / 2.0 < 0.40:
            return None
    return EntrySignal(side, token, ask)


def entry_signal(q: Quote, cfg: Config) -> EntrySignal | None:
    if not (cfg.min_entry_seconds_left <= q.seconds_left <= cfg.entry_window_max_sec):
        return None
    cands = []
    if q.up_ask is not None and cfg.threshold <= q.up_ask <= cfg.max_entry_price:
        cands.append(EntrySignal("UP", q.up_token, q.up_ask))
    if q.dn_ask is not None and cfg.threshold <= q.dn_ask <= cfg.max_entry_price:
        cands.append(EntrySignal("DOWN", q.dn_token, q.dn_ask))
    if not cands:
        return None
    return sorted(cands, key=lambda c: c.ask, reverse=True)[0]


def should_exit(side: str, entry_price: float, q: Quote, cfg: Config) -> str | None:
    """Return exit reason ('stop_loss'|'time_exit') or None to hold."""
    if side == "UP":
        bid, ask = q.up_bid, q.up_ask
    else:
        bid, ask = q.dn_bid, q.dn_ask
    if bid is not None and ask is not None:
        mark = (bid + ask) / 2.0
        if mark <= entry_price * (1.0 - cfg.stop_loss_pct):
            return "stop_loss"
    if q.seconds_left <= cfg.exit_before_sec:
        return "time_exit"
    return None

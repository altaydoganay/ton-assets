"""Strategy: the '0.70 favorite into close' logic, mirroring the original bot.

Entry  : inside the entry window, if a side's ask is in [threshold, max_entry_price],
         buy the stronger side (highest qualifying ask).
Exit   : stop-loss (mark <= entry*(1-stop_loss_pct)) OR seconds_left <= exit_before_sec.
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

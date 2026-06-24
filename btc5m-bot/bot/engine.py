"""Trading engine: the fully-automated loop. Start it and leave it alone.

Per tick it: discovers the imminent 5-min market, pulls its order book, and
either looks for an entry (favorite into close) or manages the open position
to its exit (stop-loss / flatten before close). All risk checks happen here.
"""
from __future__ import annotations
import time
from dataclasses import dataclass

from . import market, strategy
from .broker import Broker, Fill
from .config import Config
from .risk import RiskManager
from .state import State


@dataclass
class Position:
    market_id: str
    slug: str
    side: str
    token: str
    entry_price: float
    shares: float
    stake_usd: float


class TradingEngine:
    def __init__(self, cfg: Config, broker: Broker, state: State,
                 risk: RiskManager, logger):
        self.cfg = cfg
        self.broker = broker
        self.state = state
        self.risk = risk
        self.log = logger
        self.pos: Position | None = None
        self._last_hb = 0.0
        self._hb_every = 30.0   # heartbeat status line cadence (seconds)

    # ---- main loop ---------------------------------------------------------
    def run(self):
        c = self.cfg
        self.log.info(f"Engine start | broker={self.broker.name()} | "
                      f"threshold={c.threshold} max_entry={c.max_entry_price} "
                      f"stake=${c.stake_usd} stop={c.stop_loss_pct} "
                      f"exit_before={c.exit_before_sec}s poll={c.poll_sec}s")
        self.log.info(f"Balance(demo)=${self.state.data['balance_usd']:.2f} "
                      f"PnL_total=${self.state.data['realized_pnl_total']:+.2f}")
        while True:
            try:
                self.tick()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.log.warning(f"tick error: {type(e).__name__}: {e}")
            time.sleep(c.poll_sec)

    # ---- one iteration -----------------------------------------------------
    def tick(self):
        self.state.roll_day()

        if self.pos is None:
            self._look_for_entry()
        else:
            self._manage_open()

    def _look_for_entry(self):
        ok, why = self.risk.can_open()
        target = market.pick_target(self.cfg.asset,
                                    min_seconds_left=self.cfg.exit_before_sec + 5)
        if target is None:
            return
        if self.state.already_traded(target["market_id"]):
            return
        q = market.quote(target)
        self._heartbeat(q, ok, why)
        if not ok:
            return

        sig = strategy.entry_signal(q, self.cfg)
        if sig is None:
            return
        stake, shares = self.risk.position_stake(sig.ask)
        if shares <= 0:
            return
        fill = self.broker.buy(sig.token, sig.ask, shares)
        if not fill.ok:
            self.log.warning(f"entry rejected: {fill.info}")
            return
        self.pos = Position(q.market_id, q.slug, sig.side, sig.token,
                            fill.price, fill.shares, stake)
        self.log.info(f"ENTER {sig.side} {q.slug} @ {fill.price:.3f} "
                      f"x{fill.shares:.2f} (${stake:.2f}) | {q.seconds_left}s left")

    def _heartbeat(self, q, can_open, why):
        now = time.time()
        if now - self._last_hb < self._hb_every:
            return
        self._last_hb = now
        gate = "ready" if can_open else f"blocked({why})"
        self.log.info(
            f"[hb] {q.slug} {q.seconds_left}s left | UP ask={q.up_ask} "
            f"DN ask={q.dn_ask} | {gate} | "
            f"bal ${self.state.data['balance_usd']:.2f} "
            f"day PnL ${self.state.data['realized_pnl_today']:+.2f} "
            f"trades {self.state.data['trades_today']}")

    def _manage_open(self):
        p = self.pos
        target = {"market_id": p.market_id, "slug": p.slug, "end_ts": None,
                  "up_token": p.token, "dn_token": p.token}
        # we only need this side's book; re-discover end_ts via slug timestamp
        end_ts = market._end_ts_from_slug(p.slug)
        target["end_ts"] = end_ts
        q = market.quote(target)

        reason = strategy.should_exit(p.side, p.entry_price, q, self.cfg)
        if reason is None:
            return
        bid = q.up_bid if p.side == "UP" else q.dn_bid
        exit_px = bid if bid is not None else max(p.entry_price * 0.5, 0.01)
        fill = self.broker.sell(p.token, exit_px, p.shares)
        if not fill.ok:
            self.log.warning(f"exit order failed: {fill.info} (will retry next tick)")
            return
        pnl = (fill.price - p.entry_price) * p.shares
        bal_delta = fill.price * p.shares - p.stake_usd  # demo bankroll change
        self.state.record_trade(pnl, bal_delta, p.market_id)
        self.log.info(f"EXIT  {p.side} {p.slug} @ {fill.price:.3f} ({reason}) | "
                      f"PnL ${pnl:+.3f} | day ${self.state.data['realized_pnl_today']:+.2f} "
                      f"| bal ${self.state.data['balance_usd']:.2f}")
        self.pos = None

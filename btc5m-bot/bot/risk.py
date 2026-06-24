"""Risk manager: daily loss cap, trade count, position sizing, kill switch."""
from __future__ import annotations
import os

from .config import Config
from .state import State


KILL_FILE = "STOP"     # create a file named STOP in the working dir to halt trading


class RiskManager:
    def __init__(self, cfg: Config, state: State):
        self.cfg = cfg
        self.state = state

    def kill_switch_active(self) -> bool:
        return os.path.exists(KILL_FILE)

    def can_open(self) -> tuple[bool, str]:
        s = self.state.data
        if self.kill_switch_active():
            return False, "kill switch (STOP file present)"
        if s.get("halted"):
            return False, "daily loss cap reached (halted)"
        if -s["realized_pnl_today"] >= self.cfg.daily_max_loss_usd:
            s["halted"] = True
            self.state.save()
            return False, "daily loss cap reached"
        if s["trades_today"] >= self.cfg.max_trades_per_day:
            return False, "max trades/day reached"
        return True, ""

    def position_stake(self, entry_price: float) -> tuple[float, float]:
        """Return (stake_usd, shares) respecting the notional cap."""
        stake = min(self.cfg.stake_usd, self.cfg.max_notional_usd)
        # never let the position exceed remaining loss budget
        remaining = self.cfg.daily_max_loss_usd + self.state.data["realized_pnl_today"]
        stake = max(0.0, min(stake, remaining))
        shares = stake / entry_price if entry_price > 0 else 0.0
        return stake, shares

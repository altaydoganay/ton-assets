"""Persistent daily state: balance, realized PnL, trade counts, kill switch."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone


class State:
    def __init__(self, path: str, demo_starting_balance: float):
        self.path = path
        self._default_balance = demo_starting_balance
        self.data = {
            "day": self._today(),
            "balance_usd": demo_starting_balance,   # demo bankroll (tracked locally)
            "realized_pnl_total": 0.0,
            "realized_pnl_today": 0.0,
            "trades_today": 0,
            "traded_market_ids": [],
            "halted": False,                        # tripped by daily loss cap
        }
        self._load()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data.update(json.load(f))
        self.roll_day()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def roll_day(self):
        today = self._today()
        if self.data.get("day") != today:
            self.data["day"] = today
            self.data["realized_pnl_today"] = 0.0
            self.data["trades_today"] = 0
            self.data["traded_market_ids"] = []
            self.data["halted"] = False
            self.save()

    # convenience
    def record_trade(self, pnl_usd: float, balance_delta: float, market_id: str):
        self.data["realized_pnl_total"] += pnl_usd
        self.data["realized_pnl_today"] += pnl_usd
        self.data["balance_usd"] += balance_delta
        self.data["trades_today"] += 1
        if market_id not in self.data["traded_market_ids"]:
            self.data["traded_market_ids"].append(market_id)
        self.save()

    def already_traded(self, market_id: str) -> bool:
        return market_id in self.data["traded_market_ids"]

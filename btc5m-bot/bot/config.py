"""Configuration loading: YAML file + environment (.env) overrides."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Config:
    # mode
    mode: str = "demo"                     # "demo" (paper) or "live" (real money)
    asset: str = "btc"                    # market family: btc-updown-5m

    # strategy
    threshold: float = 0.70               # enter favorite when its ask >= this
    max_entry_price: float = 0.90         # ...but never pay above this
    stop_loss_pct: float = 0.25           # exit if mark falls this % below entry
    exit_before_sec: int = 20             # always flatten this many sec before close
    entry_window_max_sec: int = 150       # only consider entering inside this window
    min_entry_seconds_left: int = 60      # ...and not later than this

    # sizing / risk
    stake_usd: float = 5.0                # nominal stake per trade
    max_notional_usd: float = 8.0         # hard cap on a single position
    daily_max_loss_usd: float = 25.0      # stop trading for the day past this loss
    max_trades_per_day: int = 12
    slippage_bps: float = 10.0            # modeled adverse fill (demo) / tolerance

    # demo
    demo_starting_balance_usd: float = 1000.0

    # loop
    poll_sec: int = 3

    # live (secrets come from env, never the yaml)
    clob_host: str = "https://clob.polymarket.com"
    chain_id: int = 137

    # internal
    raw: dict = field(default_factory=dict)


def load_config(path: str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    known = Config().__dict__.keys()
    kwargs = {k: v for k, v in data.items() if k in known and k != "raw"}
    cfg = Config(**kwargs)
    cfg.raw = data
    # env override for mode is handy for scripting
    cfg.mode = os.getenv("BOT_MODE", cfg.mode).lower()
    return cfg

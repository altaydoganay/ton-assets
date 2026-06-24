#!/usr/bin/env python3
"""
5min BTC Polymarket bot — entrypoint.

  python main.py --config config.yaml          # demo (paper) by default
  BOT_MODE=live python main.py --config config.yaml --i-understand-live

Demo moves NO money. Live mode trades REAL USDC on Polymarket and is gated
behind an explicit flag + a typed confirmation + the PRIVATE_KEY env var.
"""
from __future__ import annotations
import argparse
import sys

from bot.config import load_config
from bot.log import setup_logging
from bot.state import State
from bot.risk import RiskManager
from bot.broker import make_broker
from bot.engine import TradingEngine


def confirm_live() -> bool:
    print("\n" + "=" * 70)
    print(" LIVE MODE — this will place REAL orders with REAL money on Polymarket.")
    print(" This strategy has NEGATIVE expected value in backtests. You can lose")
    print(" your funds. Daily loss cap and the STOP kill-switch still apply.")
    print("=" * 70)
    try:
        ans = input(' Type exactly  I ACCEPT THE RISK  to continue: ').strip()
    except EOFError:
        return False
    return ans == "I ACCEPT THE RISK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--i-understand-live", action="store_true",
                    help="required flag to even attempt live mode")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging()

    if cfg.mode == "live":
        if not args.i_understand_live:
            log.error("Live mode requires --i-understand-live. Refusing to start.")
            sys.exit(2)
        if not confirm_live():
            log.error("Live confirmation not given. Exiting.")
            sys.exit(2)
        log.warning("LIVE MODE ENABLED — real money.")
    else:
        log.info("DEMO MODE — paper trading, no real money.")

    state = State(args.state, cfg.demo_starting_balance_usd)
    risk = RiskManager(cfg, state)
    broker = make_broker(cfg)
    engine = TradingEngine(cfg, broker, state, risk, log)

    log.info("Create a file named STOP in this directory at any time to halt trading.")
    try:
        engine.run()
    except KeyboardInterrupt:
        log.info("Stopped by user (Ctrl-C). State saved.")


if __name__ == "__main__":
    main()

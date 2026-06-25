"""Deterministic offline test of the full engine path (ENTER -> EXIT -> PnL).

Monkeypatches market discovery/quoting with scripted quotes so we can verify
entry, stop-loss exit, time exit, PnL accounting and state — without waiting
for live market conditions.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import market
from bot.config import Config
from bot.state import State
from bot.risk import RiskManager
from bot.broker import PaperBroker
from bot.engine import TradingEngine
from bot.market import Quote
from bot.log import setup_logging


def mk_quote(slug, sl, up_bid, up_ask, dn_bid, dn_ask):
    return Quote(market_id=slug.split("-")[-1], slug=slug, end_ts=0, seconds_left=sl,
                 up_token="UPTOK", dn_token="DNTOK",
                 up_bid=up_bid, up_ask=up_ask, dn_bid=dn_bid, dn_ask=dn_ask)


def run():
    cfg = Config(mode="demo", signal_mode="book_threshold",
                 threshold=0.70, max_entry_price=0.90,
                 stop_loss_pct=0.25, exit_before_sec=20,
                 entry_window_max_sec=150, min_entry_seconds_left=30,
                 stake_usd=5.0, max_notional_usd=8.0, slippage_bps=0.0)
    tmp = tempfile.mkdtemp()
    state = State(os.path.join(tmp, "state.json"), 1000.0)
    risk = RiskManager(cfg, state)
    log = setup_logging(os.path.join(tmp, "logs"))
    eng = TradingEngine(cfg, PaperBroker(cfg), state, risk, log)

    # Scripted timeline: (slug, seconds_left, up_bid, up_ask, dn_bid, dn_ask)
    script = [
        # Market A: enter UP @0.72, then stop-loss when mark collapses
        ("btc-updown-5m-A", 120, 0.71, 0.72, 0.28, 0.29),   # ENTER UP
        ("btc-updown-5m-A",  90, 0.49, 0.51, 0.49, 0.51),   # mark 0.50 <= 0.54 -> STOP
        # Market B: enter DOWN @0.80, hold, then time-exit near close in profit
        ("btc-updown-5m-B", 130, 0.18, 0.20, 0.79, 0.80),   # ENTER DOWN
        ("btc-updown-5m-B",  15, 0.05, 0.07, 0.92, 0.94),   # time_exit @0.92 bid
    ]
    idx = {"i": 0}

    def fake_pick(asset, min_seconds_left=5, lookahead_rounds=6):
        if idx["i"] >= len(script):
            return None
        slug = script[idx["i"]][0]
        return {"market_id": slug.split("-")[-1], "slug": slug, "end_ts": 0,
                "up_token": "UPTOK", "dn_token": "DNTOK"}

    def fake_quote(target):
        row = script[idx["i"]]
        return mk_quote(*row)

    market.pick_target = fake_pick
    market.quote = fake_quote

    results = []
    for _ in range(len(script)):
        eng.tick()
        results.append((eng.pos.side if eng.pos else None,
                        round(state.data["realized_pnl_today"], 4),
                        state.data["trades_today"]))
        idx["i"] += 1

    print("step-by-step (open_side, pnl_today, trades):")
    for r in results:
        print("  ", r)
    print("final balance:", round(state.data["balance_usd"], 4))
    print("total trades :", state.data["trades_today"])

    # assertions
    assert state.data["trades_today"] == 2, "expected 2 closed trades"
    # exits fill at the BID. A: buy 6.944sh @0.72, sell @0.49 (stop).
    #                        B: buy 6.25 sh @0.80, sell @0.92 (time exit).
    pnl_a = (0.49 - 0.72) * (5.0 / 0.72)
    pnl_b = (0.92 - 0.80) * (5.0 / 0.80)
    expected = round(pnl_a + pnl_b, 2)
    got = round(state.data["realized_pnl_today"], 2)
    assert got == expected, f"pnl mismatch: got {got} expected {expected}"
    print(f"\nPASS  pnl={got} (A={pnl_a:+.3f}, B={pnl_b:+.3f})")


if __name__ == "__main__":
    run()

"""Deterministic offline test of the btc_move strategy through the full engine.

Monkeypatches market discovery/quoting AND the BTC feeds so we can drive a
complete ENTER (BTC moved past threshold) -> EXIT (time exit) cycle without
the network or live market timing.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import market, feeds
from bot.config import Config
from bot.state import State
from bot.risk import RiskManager
from bot.broker import PaperBroker
from bot.engine import TradingEngine
from bot.market import Quote
from bot.log import setup_logging


def mk_quote(slug, sl, up_bid, up_ask, dn_bid, dn_ask, end_ts):
    return Quote(market_id=slug.split("-")[-1], slug=slug, end_ts=end_ts,
                 seconds_left=sl, up_token="UPTOK", dn_token="DNTOK",
                 up_bid=up_bid, up_ask=up_ask, dn_bid=dn_bid, dn_ask=dn_ask)


def run():
    cfg = Config(mode="demo", signal_mode="btc_move", move_threshold_usd=20.0,
                 max_entry_price=0.90, stop_loss_pct=0.25,
                 exit_before_sec=5, entry_window_max_sec=120,
                 min_entry_seconds_left=10, stake_usd=5.0, slippage_bps=0.0)
    tmp = tempfile.mkdtemp()
    state = State(os.path.join(tmp, "state.json"), 1000.0)
    risk = RiskManager(cfg, state)
    log = setup_logging(os.path.join(tmp, "logs"))
    eng = TradingEngine(cfg, PaperBroker(cfg), state, risk, log)

    STRIKE = 61000.0
    # timeline: (slug, sec_left, up_bid, up_ask, dn_bid, dn_ask, spot)
    script = [
        # BTC +45 over strike, inside window -> ENTER UP @ up_ask 0.55
        ("btc-updown-5m-A", 90, 0.54, 0.55, 0.45, 0.46, STRIKE + 45),
        # still UP favored, book drifted up; sec_left<=exit_before -> time EXIT @ bid 0.66
        ("btc-updown-5m-A",  4, 0.66, 0.67, 0.33, 0.34, STRIKE + 60),
    ]
    idx = {"i": 0}

    def fake_pick(asset, min_seconds_left=5, lookahead_rounds=6):
        if idx["i"] >= len(script):
            return None
        slug = script[idx["i"]][0]
        return {"market_id": slug.split("-")[-1], "slug": slug, "end_ts": 1000,
                "up_token": "UPTOK", "dn_token": "DNTOK"}

    def fake_quote(target):
        row = script[idx["i"]]
        return mk_quote(row[0], row[1], row[2], row[3], row[4], row[5], end_ts=1000)

    market.pick_target = fake_pick
    market.quote = fake_quote
    feeds.btc_spot = lambda: script[idx["i"]][6]
    feeds.btc_minute_open = lambda ts: STRIKE

    for _ in range(len(script)):
        eng.tick()
        idx["i"] += 1

    pnl = round(state.data["realized_pnl_today"], 4)
    bal = round(state.data["balance_usd"], 4)
    print(f"trades={state.data['trades_today']} pnl={pnl} bal={bal}")

    # entered UP @0.55 (5/0.55=9.09 sh), exited @0.66 bid -> pnl=(0.66-0.55)*9.09
    expected = round((0.66 - 0.55) * (5.0 / 0.55), 2)
    assert state.data["trades_today"] == 1, "expected exactly 1 trade"
    assert round(pnl, 2) == expected, f"pnl {pnl} != {expected}"
    print(f"\nPASS  btc_move ENTER UP -> time EXIT, pnl={pnl} (exp {expected})")


if __name__ == "__main__":
    run()

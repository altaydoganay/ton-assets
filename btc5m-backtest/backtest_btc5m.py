#!/usr/bin/env python3
"""
Backtest skeleton for the "0.70 favorite into close" strategy used by the
5min-btc-polymarket bot (https://github.com/Novals83/5min-btc-polymarket).

What the real bot actually does (per its runner code):
  - Poll the CLOB best ask for UP and DOWN.
  - When a side's ask >= threshold (default 0.70), BUY that side (the favorite).
  - EXIT at `exit_before_sec` (default 20s before close) OR on stop-loss
    (price falls stop_loss_pct below entry).
  - It does NOT hold to settlement, so PnL = secondary-market price change
    in the final ~100s, NOT the binary $1 payout.

This script measures the strategy's REAL win-rate and expected value (EV)
after costs, under a configurable market model.

KEY MODELLING CHOICE
--------------------
By default the simulated price is an efficient martingale (no edge). Under
this assumption the only thing that moves EV is COST (spread + fees +
slippage), so EV should come out negative. That is the null hypothesis.

To test the bot's actual thesis ("momentum follows through into close"),
inject return autocorrelation with --momentum RHO (>0 = trending,
<0 = mean-reverting). This lets you answer: *how much momentum would the
market need for this strategy to overcome its costs?*

Replace `SyntheticDataSource` with a real adapter (see README.md) to run it
on historical Polymarket CLOB snapshots + BTC spot.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
from dataclasses import dataclass, field

SECONDS_PER_YEAR = 365 * 24 * 3600


# --------------------------------------------------------------------------- #
# Math helpers
# --------------------------------------------------------------------------- #
def norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (no numpy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Market data model
# --------------------------------------------------------------------------- #
@dataclass
class Quote:
    seconds_left: int
    up_bid: float
    up_ask: float
    dn_bid: float
    dn_ask: float


@dataclass
class Market:
    quotes: list[Quote]          # ordered from open -> close
    up_wins: bool                # realized binary outcome (S_close > strike)


class SyntheticDataSource:
    """
    Generates fair-by-construction 5-minute UP/DOWN markets.

    BTC follows a (optionally autocorrelated) random walk. The order-book mid
    for each side equals the interim true probability that the side finishes
    in the money; ask/bid are mid +/- half_spread plus microstructure noise.

    Because the full path is simulated, the win/loss outcome is REAL, not
    drawn from the quoted price. With momentum=0 the price is a martingale,
    so the strategy can only lose to costs -- that is the whole point.
    """

    def __init__(
        self,
        s0: float = 60_000.0,
        vol_annual: float = 0.60,
        spread: float = 0.02,
        quote_noise: float = 0.01,
        momentum: float = 0.0,
        horizon_sec: int = 300,
        poll_sec: int = 5,
        seed: int | None = None,
    ):
        self.s0 = s0
        self.vol_annual = vol_annual
        self.spread = spread
        self.quote_noise = quote_noise
        self.momentum = momentum          # AR(1) coefficient on per-second shocks
        self.horizon_sec = horizon_sec
        self.poll_sec = poll_sec
        self.rng = random.Random(seed)

    def _fair_up_prob(self, s: float, strike: float, seconds_left: int) -> float:
        if seconds_left <= 0:
            return 1.0 if s > strike else 0.0
        tau = seconds_left / SECONDS_PER_YEAR
        sig = self.vol_annual * math.sqrt(tau)
        if sig <= 0:
            return 1.0 if s > strike else 0.0
        d = (math.log(s / strike) - 0.5 * sig * sig) / sig
        return norm_cdf(d)

    def generate(self) -> Market:
        sig_sec = self.vol_annual / math.sqrt(SECONDS_PER_YEAR)
        strike = self.s0
        s = self.s0
        prev_z = 0.0
        half = self.spread / 2.0

        quotes: list[Quote] = []
        for t in range(self.horizon_sec):
            seconds_left = self.horizon_sec - t
            # AR(1) shock: momentum>0 -> trending, <0 -> mean-reverting
            eps = self.rng.gauss(0.0, 1.0)
            z = self.momentum * prev_z + math.sqrt(1.0 - self.momentum ** 2) * eps
            prev_z = z
            s *= math.exp(sig_sec * z - 0.5 * sig_sec * sig_sec)

            if seconds_left % self.poll_sec == 0:
                p_up = self._fair_up_prob(s, strike, seconds_left)
                n1 = self.rng.gauss(0.0, self.quote_noise)
                up_mid = clip(p_up + n1, 0.01, 0.99)
                dn_mid = clip(1.0 - up_mid, 0.01, 0.99)
                quotes.append(
                    Quote(
                        seconds_left=seconds_left,
                        up_bid=clip(up_mid - half, 0.01, 0.99),
                        up_ask=clip(up_mid + half, 0.01, 0.99),
                        dn_bid=clip(dn_mid - half, 0.01, 0.99),
                        dn_ask=clip(dn_mid + half, 0.01, 0.99),
                    )
                )

        up_wins = s > strike
        return Market(quotes=quotes, up_wins=up_wins)


# --------------------------------------------------------------------------- #
# Strategy
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    threshold: float = 0.70
    stop_loss_pct: float = 0.25
    exit_before_sec: int = 20
    min_entry_seconds_left: int = 60
    entry_window_max_sec: int = 150     # only enter when seconds_left <= this
    fee_bps: float = 0.0                # per side, on notional (Polymarket: 0 today)
    slippage_bps: float = 10.0          # extra adverse fill on exit
    max_entry_price: float = 1.0        # skip entries priced above this (discipline)


@dataclass
class Trade:
    side: str
    entry_price: float
    exit_price: float
    reason: str          # "stop_loss" | "time_exit"
    net_return: float    # PnL per $1 of stake, after costs


def run_strategy(m: Market, p: Params) -> Trade | None:
    """Mirror the bot: buy the favorite when ask>=threshold inside the entry
    window; mark to mid; exit at stop-loss or exit_before_sec (sell at bid)."""
    entry = None  # (side, entry_ask)
    for q in m.quotes:
        if entry is None:
            if not (p.min_entry_seconds_left <= q.seconds_left <= p.entry_window_max_sec):
                continue
            cands = []
            if p.threshold <= q.up_ask <= p.max_entry_price:
                cands.append(("UP", q.up_ask))
            if p.threshold <= q.dn_ask <= p.max_entry_price:
                cands.append(("DOWN", q.dn_ask))
            if cands:
                cands.sort(key=lambda x: x[1], reverse=True)
                entry = cands[0]
            continue

        side, entry_ask = entry
        cur_mid = (q.up_bid + q.up_ask) / 2 if side == "UP" else (q.dn_bid + q.dn_ask) / 2
        cur_bid = q.up_bid if side == "UP" else q.dn_bid
        sl_price = entry_ask * (1.0 - p.stop_loss_pct)

        if cur_mid <= sl_price:
            return _close(side, entry_ask, cur_bid, "stop_loss", p)
        if q.seconds_left <= p.exit_before_sec:
            return _close(side, entry_ask, cur_bid, "time_exit", p)

    # never hit exit window inside available quotes: close at last bid
    if entry is not None:
        side, entry_ask = entry
        last = m.quotes[-1]
        cur_bid = last.up_bid if side == "UP" else last.dn_bid
        return _close(side, entry_ask, cur_bid, "time_exit", p)
    return None


def _close(side, entry_ask, exit_bid, reason, p: Params) -> Trade:
    # buy at ask, sell at bid; fees + slippage on the exit fill
    exit_fill = exit_bid * (1.0 - p.slippage_bps / 1e4)
    fees = (entry_ask + exit_fill) * (p.fee_bps / 1e4)
    pnl_per_share = exit_fill - entry_ask - fees
    net_return = pnl_per_share / entry_ask      # per $1 of stake
    return Trade(side, entry_ask, exit_fill, reason, net_return)


# --------------------------------------------------------------------------- #
# Backtest driver + metrics
# --------------------------------------------------------------------------- #
def backtest(src: SyntheticDataSource, p: Params, n_markets: int, stake_usd: float):
    trades: list[Trade] = []
    for _ in range(n_markets):
        t = run_strategy(src.generate(), p)
        if t is not None:
            trades.append(t)

    print(f"\n{'='*64}")
    print(f"Markets simulated      : {n_markets}")
    print(f"Trades taken           : {len(trades)}  "
          f"({100*len(trades)/n_markets:.1f}% of markets triggered)")
    if not trades:
        print("No trades triggered -- threshold never crossed in entry window.")
        return

    rets = [t.net_return for t in trades]
    wins = [r for r in rets if r > 0]
    win_rate = len(wins) / len(rets)
    avg = statistics.mean(rets)
    sd = statistics.pstdev(rets)
    sl_hits = sum(1 for t in trades if t.reason == "stop_loss")

    print(f"Win rate (net>0)       : {100*win_rate:.1f}%")
    print(f"Stop-loss exits        : {100*sl_hits/len(trades):.1f}%")
    print(f"Avg net return / trade : {100*avg:+.3f}%  "
          f"(${avg*stake_usd:+.3f} on ${stake_usd:.0f} stake)")
    print(f"Std dev / trade        : {100*sd:.3f}%")
    if sd > 0:
        print(f"Sharpe per trade       : {avg/sd:+.3f}")
    print(f"Total net PnL          : ${sum(rets)*stake_usd:+.2f} "
          f"over {len(trades)} trades")

    # equity curve / max drawdown (compounding the per-trade returns)
    equity, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)
    print(f"Final equity (x start) : {equity:.3f}")
    print(f"Max drawdown           : {100*mdd:.1f}%")

    verdict = "POSITIVE EV ✅" if avg > 0 else "NEGATIVE EV ❌ (loses to costs)"
    print(f"\nVERDICT: avg net EV per trade is {verdict}")
    print(f"{'='*64}\n")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # strategy (mirrors the real runner flags)
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--stop-loss-pct", type=float, default=0.25)
    ap.add_argument("--exit-before-sec", type=int, default=20)
    ap.add_argument("--min-entry-seconds-left", type=int, default=60)
    ap.add_argument("--entry-window-max-sec", type=int, default=150)
    ap.add_argument("--max-entry-price", type=float, default=1.0,
                    help="skip entries priced above this (entry discipline)")
    ap.add_argument("--stake-usd", type=float, default=5.0)
    # cost model
    ap.add_argument("--fee-bps", type=float, default=0.0)
    ap.add_argument("--slippage-bps", type=float, default=10.0)
    # market model
    ap.add_argument("--spread", type=float, default=0.02,
                    help="full bid/ask spread in probability units")
    ap.add_argument("--vol-annual", type=float, default=0.60)
    ap.add_argument("--momentum", type=float, default=0.0,
                    help="AR(1) coef on returns: >0 trending (tests the thesis), "
                         "<0 mean-reverting, 0 = efficient/martingale")
    ap.add_argument("--quote-noise", type=float, default=0.01)
    # run
    ap.add_argument("--n-markets", type=int, default=20_000)
    ap.add_argument("--poll-sec", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    return ap


def main():
    args = build_argparser().parse_args()
    src = SyntheticDataSource(
        vol_annual=args.vol_annual,
        spread=args.spread,
        quote_noise=args.quote_noise,
        momentum=args.momentum,
        poll_sec=args.poll_sec,
        seed=args.seed,
    )
    p = Params(
        threshold=args.threshold,
        stop_loss_pct=args.stop_loss_pct,
        exit_before_sec=args.exit_before_sec,
        min_entry_seconds_left=args.min_entry_seconds_left,
        entry_window_max_sec=args.entry_window_max_sec,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        max_entry_price=args.max_entry_price,
    )
    print(f"\nConfig: threshold={p.threshold}  stop_loss={p.stop_loss_pct}  "
          f"spread={args.spread}  slippage_bps={args.slippage_bps}  "
          f"momentum(rho)={args.momentum}")
    backtest(src, p, args.n_markets, args.stake_usd)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
P/L simulation of the 5min-btc-polymarket "0.70 favorite" strategy driven by
the LAST ~60 MINUTES OF REAL BTC PRICE (Kraken 1-min OHLC).

Method / honesty note
---------------------
I do not have historical Polymarket CLOB snapshots, so the order book is
RECONSTRUCTED from real BTC moves under an efficient-pricing assumption:
each side's mid = the true probability it finishes in the money (strike =
price at the 5-min window open), ask/bid = mid +/- half-spread. Realized
vol is estimated from the same hour of data. Outcomes are REAL (close vs
strike). This isolates the cost drag on genuine recent volatility; it does
NOT inject any mispricing edge for or against the bot.

12 markets is an anecdote, not statistics -- see backtest_btc5m.py for the
20k-market result. This just answers: "on the actual last hour of BTC, what
would this bot have done?"
"""
from __future__ import annotations
import argparse, json, math, statistics, urllib.request
from backtest_btc5m import norm_cdf, clip, Params, Quote, Market, run_strategy

SECONDS_PER_YEAR = 365 * 24 * 3600


def fetch_kraken_1m(minutes: int = 62):
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.load(r)
    res = d["result"]
    key = [k for k in res if k != "last"][0]
    rows = res[key]              # [time, open, high, low, close, vwap, vol, count]
    rows = rows[-(minutes + 1):]
    times = [int(x[0]) for x in rows]
    closes = [float(x[4]) for x in rows]
    return times, closes


def price_at(second_abs, anchor_t, anchor_p):
    """Linear interpolation of close-to-close path at an absolute second."""
    if second_abs <= anchor_t[0]:
        return anchor_p[0]
    if second_abs >= anchor_t[-1]:
        return anchor_p[-1]
    for i in range(len(anchor_t) - 1):
        if anchor_t[i] <= second_abs <= anchor_t[i + 1]:
            f = (second_abs - anchor_t[i]) / (anchor_t[i + 1] - anchor_t[i])
            return anchor_p[i] + f * (anchor_p[i + 1] - anchor_p[i])
    return anchor_p[-1]


def fair_up(s, strike, seconds_left, vol_annual):
    if seconds_left <= 0:
        return 1.0 if s > strike else 0.0
    sig = vol_annual * math.sqrt(seconds_left / SECONDS_PER_YEAR)
    if sig <= 0:
        return 1.0 if s > strike else 0.0
    d = (math.log(s / strike) - 0.5 * sig * sig) / sig
    return norm_cdf(d)


def build_market(anchor_t, anchor_p, win_start, vol_annual, spread, poll_sec, horizon=300):
    strike = price_at(win_start, anchor_t, anchor_p)
    half = spread / 2.0
    quotes = []
    for sl in range(horizon, 0, -poll_sec):
        t_abs = win_start + (horizon - sl)
        s = price_at(t_abs, anchor_t, anchor_p)
        p = clip(fair_up(s, strike, sl, vol_annual), 0.01, 0.99)
        dn = 1.0 - p
        quotes.append(Quote(sl,
                            clip(p - half, .01, .99), clip(p + half, .01, .99),
                            clip(dn - half, .01, .99), clip(dn + half, .01, .99)))
    s_close = price_at(win_start + horizon, anchor_t, anchor_p)
    return Market(quotes=quotes, up_wins=s_close > strike), strike, s_close


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--stop-loss-pct", type=float, default=0.25)
    ap.add_argument("--exit-before-sec", type=int, default=20)
    ap.add_argument("--min-entry-seconds-left", type=int, default=60)
    ap.add_argument("--entry-window-max-sec", type=int, default=150)
    ap.add_argument("--stake-usd", type=float, default=5.0)
    ap.add_argument("--spread", type=float, default=0.02)
    ap.add_argument("--slippage-bps", type=float, default=10.0)
    ap.add_argument("--fee-bps", type=float, default=0.0)
    ap.add_argument("--poll-sec", type=int, default=5)
    args = ap.parse_args()

    times, closes = fetch_kraken_1m(62)
    # anchors: one point per minute close
    anchor_t = times[:]
    anchor_p = closes[:]
    t0 = anchor_t[0]
    anchor_t = [t - t0 for t in anchor_t]      # zero-based seconds

    # realized annualized vol from 1-min log returns
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    sd_1m = statistics.pstdev(rets)
    vol_annual = sd_1m * math.sqrt(SECONDS_PER_YEAR / 60.0)

    p = Params(args.threshold, args.stop_loss_pct, args.exit_before_sec,
               args.min_entry_seconds_left, args.entry_window_max_sec,
               args.fee_bps, args.slippage_bps)

    total_minutes = (anchor_t[-1]) // 60
    n_windows = min(12, total_minutes // 5)
    print(f"\nReal BTC last {n_windows*5} min | spot ~${closes[-1]:,.0f} | "
          f"realized vol(ann) ~{vol_annual*100:.0f}% | spread={args.spread} "
          f"slip={args.slippage_bps}bps")
    print(f"{'-'*72}")
    print(f"{'#':>2} {'open$':>9} {'close$':>9} {'res':>4} {'side':>4} "
          f"{'entry':>6} {'exit':>6} {'why':>10} {'net%':>7} {'$PnL':>7}")
    print(f"{'-'*72}")

    total = 0.0
    rets_list = []
    for i in range(n_windows):
        win_start = i * 5 * 60
        m, strike, s_close = build_market(anchor_t, anchor_p, win_start,
                                          vol_annual, args.spread, args.poll_sec)
        res = "UP" if m.up_wins else "DN"
        tr = run_strategy(m, p)
        if tr is None:
            print(f"{i+1:>2} {strike:>9,.0f} {s_close:>9,.0f} {res:>4} "
                  f"{'--':>4} {'--':>6} {'--':>6} {'no-trade':>10} {'--':>7} {'--':>7}")
            continue
        pnl = tr.net_return * args.stake_usd
        total += pnl
        rets_list.append(tr.net_return)
        print(f"{i+1:>2} {strike:>9,.0f} {s_close:>9,.0f} {res:>4} {tr.side:>4} "
              f"{tr.entry_price:>6.3f} {tr.exit_price:>6.3f} {tr.reason:>10} "
              f"{tr.net_return*100:>+6.2f} {pnl:>+7.3f}")

    print(f"{'-'*72}")
    n = len(rets_list)
    if n:
        wr = sum(1 for r in rets_list if r > 0) / n
        print(f"Trades: {n}/{n_windows}   Win rate: {wr*100:.0f}%   "
              f"Avg net/trade: {statistics.mean(rets_list)*100:+.2f}%")
    print(f"TOTAL P/L over last hour: ${total:+.3f}  "
          f"(on ${args.stake_usd:.0f} stake/trade)\n")


if __name__ == "__main__":
    main()

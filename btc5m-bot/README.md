# BTC 5-min Polymarket Bot (demo + live)

Fully-automated trading bot for Polymarket's `btc-updown-5m` markets. You start
it once and leave it; it discovers the imminent 5-minute round, watches the
order book, enters the favorite near close, and manages the exit — all by itself.

It runs in two modes:

- **demo** (default): paper trading. Uses **real** live BTC + **real** Polymarket
  order books, but fills are simulated and **no money moves**.
- **live**: places **real USDC orders** on Polymarket via the official
  `py-clob-client`. Gated behind an explicit flag + a typed confirmation.

> ⚠️ **Read this.** In every backtest in this project the strategy has
> **negative expected value** after costs (see `../btc5m-backtest/`). Live mode
> can and likely will **lose your money**. Use demo to learn; risk only what you
> can afford to lose. This is software, not financial advice.

---

## Quick start (demo — safe)

```bash
cd btc5m-bot
./run.sh                # creates a venv, installs deps, starts paper trading
```

You'll see a heartbeat like:

```
[hb] btc-updown-5m-1782312900 125s left | UP ask=0.51 DN ask=0.5 | ready | bal $1000.00 day PnL $+0.00 trades 0
ENTER UP btc-updown-5m-... @ 0.720 x6.94 ($5.00) | 118s left
EXIT  UP btc-updown-5m-... @ 0.690 (time_exit) | PnL $-0.21 | day $-0.21 | bal $999.79
```

Stop any time with **Ctrl-C**, or create a file named `STOP` in this folder to
halt trading while leaving the process running.

## Going live (real money)

1. Fund a Polygon wallet with **USDC** and set Polymarket allowances (do this
   once on polymarket.com with that wallet).
2. `cp .env.example .env` and put your wallet key in `PRIVATE_KEY`.
3. In `config.yaml` set `mode: live` (and sane caps — start tiny!).
4. Start:
   ```bash
   ./run.sh live
   ```
   You must type `I ACCEPT THE RISK` to proceed.

> The live order path is implemented against `py-clob-client` but **was not
> tested with real funds in this project**. Verify with the smallest possible
> `stake_usd` first and watch the first trades closely.

## How it works

```
feeds.py     live data: Coinbase BTC spot + Polymarket Gamma/CLOB
market.py    discovers the imminent btc-updown-5m round (slug from the clock)
strategy.py  entry (favorite ask in [threshold, max_entry_price]) + exit rules
risk.py      daily loss cap, max trades, position sizing, STOP kill-switch
broker.py    PaperBroker (demo) | PolymarketBroker (live, via py-clob-client)
engine.py    the automated loop tying it together
state.py     persists balance/PnL/trade counts across restarts (state.json)
```

Each tick (default every 3s) it finds the soonest open round, pulls both
sides' order books, and:
- **flat** → if inside the entry window and a side's ask is in
  `[threshold, max_entry_price]`, buy the stronger side;
- **in a position** → exit on stop-loss (`mark <= entry*(1-stop_loss_pct)`)
  or when `seconds_left <= exit_before_sec` (flatten before settlement).

## Configuration (`config.yaml`)

| Key | Meaning |
|---|---|
| `mode` | `demo` or `live` |
| `threshold` | enter favorite when its ask ≥ this (0.70) |
| `max_entry_price` | never pay above this (0.90) |
| `stop_loss_pct` | exit if mark falls this fraction below entry (0.25) |
| `exit_before_sec` | flatten this many seconds before close (20) |
| `entry_window_max_sec` / `min_entry_seconds_left` | when entries are allowed |
| `stake_usd` / `max_notional_usd` | per-trade size and hard cap |
| `daily_max_loss_usd` | halt trading for the day past this loss |
| `max_trades_per_day` | daily trade cap |
| `poll_sec` | loop cadence |

## Safety features

- **Demo by default** — live requires `mode: live` + `--i-understand-live` +
  typed confirmation + `PRIVATE_KEY`.
- **STOP kill-switch** — `touch STOP` halts all new entries immediately.
- **Daily loss cap** and **max trades/day** — auto-halt for the day.
- **Position sizing** never exceeds the remaining daily loss budget.
- **State persistence** — counters and balance survive restarts (`state.json`).

## Tests

```bash
python3 tests/test_engine_offline.py     # deterministic ENTER/EXIT/PnL check
```

## Limitations / honesty

- Negative expected value (proven in `../btc5m-backtest/`). No edge is claimed.
- The live broker is untested with real funds — start with a tiny stake.
- Polymarket lists rounds intermittently; when none is open the bot idles.
- Demo fills assume you take liquidity at the quoted price ± slippage; real fills
  can differ, especially in thin books near close.

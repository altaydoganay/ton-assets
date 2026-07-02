from app.core.analysis.pnl import SwapEvent, compute_performance


def test_fifo_realized_pnl_basic():
    swaps = [
        SwapEvent("MINT", "buy", sol_amount=1.0, token_amount=100, fee_sol=0.01, block_time=0),
        SwapEvent("MINT", "sell", sol_amount=2.0, token_amount=100, fee_sol=0.01, block_time=3600),
    ]
    perf = compute_performance(swaps)
    assert perf.closed_positions == 1
    # gelir 2-0.01=1.99 ; maliyet 1+0.01=1.01 ; pnl ~0.98
    assert round(perf.realized_pnl_sol, 2) == 0.98
    assert perf.win_rate == 1.0
    assert perf.open_positions == 0
    assert perf.avg_hold_seconds == 3600


def test_open_position_not_counted_as_win():
    swaps = [
        SwapEvent("MINT", "buy", sol_amount=1.0, token_amount=100, fee_sol=0.0, block_time=0),
    ]
    perf = compute_performance(swaps, current_prices={"MINT": 0.02})
    assert perf.closed_positions == 0
    assert perf.win_rate == 0.0
    assert perf.open_positions == 1
    # gerçekleşmemiş = 100*0.02 - 1.0 = 1.0
    assert round(perf.unrealized_pnl_sol, 4) == 1.0


def test_partial_sell_fifo():
    swaps = [
        SwapEvent("M", "buy", 1.0, 100, 0.0, 0),
        SwapEvent("M", "buy", 2.0, 100, 0.0, 10),
        SwapEvent("M", "sell", 1.5, 100, 0.0, 100),  # ilk lot tüketilir (maliyet 1.0)
    ]
    perf = compute_performance(swaps)
    assert perf.closed_positions == 1
    assert round(perf.realized_pnl_sol, 2) == 0.5  # 1.5 - 1.0
    assert perf.open_positions == 1  # ikinci lot açık


def test_profit_factor_and_drawdown():
    swaps = [
        SwapEvent("A", "buy", 1.0, 10, 0.0, 0),
        SwapEvent("A", "sell", 2.0, 10, 0.0, 100),   # +1.0
        SwapEvent("B", "buy", 1.0, 10, 0.0, 200),
        SwapEvent("B", "sell", 0.5, 10, 0.0, 300),   # -0.5
    ]
    perf = compute_performance(swaps)
    assert perf.closed_positions == 2
    assert round(perf.profit_factor, 2) == 2.0  # 1.0 / 0.5
    assert perf.max_drawdown_sol >= 0.5


def test_short_hold_ratio():
    swaps = [
        SwapEvent("A", "buy", 1.0, 10, 0.0, 0),
        SwapEvent("A", "sell", 1.1, 10, 0.0, 60),    # 60sn < 10dk
        SwapEvent("B", "buy", 1.0, 10, 0.0, 0),
        SwapEvent("B", "sell", 1.1, 10, 0.0, 7200),  # 2 saat
    ]
    perf = compute_performance(swaps)
    assert perf.short_hold_ratio == 0.5

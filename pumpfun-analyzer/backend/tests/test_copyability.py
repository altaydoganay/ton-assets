from app.core.analysis.copyability import CopyabilitySwap, compute_copyability
from app.core.analysis.pnl import SwapEvent, compute_performance
from app.core.scoring.wallet_scoring import WalletSignals, score_wallet
from app.api.routes_wallets import leaderboard
from app.models import Wallet, WalletStatus


def _leader_rounds(mint_prefix: str, count: int = 6):
    swaps = []
    market = []
    t = 0
    for i in range(count):
        mint = f"{mint_prefix}{i}"
        swaps.append(CopyabilitySwap(mint, "buy", 1.0, 100, 0.01, 0.0, t, "W"))
        swaps.append(CopyabilitySwap(mint, "sell", 1.5, 100, 0.015, 0.0, t + 100, "W"))
        market.append(CopyabilitySwap(mint, "buy", 1.0, 100, 0.01, 0.0, t, "M"))
        t += 200
    return swaps, market


def test_leader_wins_but_10s_follower_loses():
    leader, market = _leader_rounds("LOSE")
    full_market = []
    for row in market:
        full_market.extend([
            row,
            CopyabilitySwap(row.token_mint, "buy", 2.0, 100, 0.020, 0.0, row.block_time + 10, "M"),
            CopyabilitySwap(row.token_mint, "sell", 1.5, 100, 0.015, 0.0, row.block_time + 100, "M"),
        ])
    result = compute_copyability("W", leader, full_market, slippage=0.0, priority_fee_sol=0.0)
    metrics = result.as_metrics()
    assert metrics["copy_pnl_10s_sol"] < 0
    assert metrics["copyability_score"] < 50


def test_leader_and_10s_30s_follower_win():
    leader, market = _leader_rounds("WIN")
    full_market = []
    for row in market:
        full_market.extend([
            row,
            CopyabilitySwap(row.token_mint, "buy", 1.02, 100, 0.0102, 0.0, row.block_time + 10, "M"),
            CopyabilitySwap(row.token_mint, "buy", 1.05, 100, 0.0105, 0.0, row.block_time + 30, "M"),
            CopyabilitySwap(row.token_mint, "sell", 1.5, 100, 0.015, 0.0, row.block_time + 100, "M"),
        ])
    metrics = compute_copyability("W", leader, full_market, slippage=0.0, priority_fee_sol=0.0).as_metrics()
    assert metrics["copy_pnl_10s_sol"] > 0
    assert metrics["copy_pnl_30s_sol"] > 0
    assert metrics["copyability_score"] >= 70


def test_single_big_hit_does_not_get_top_copyability_score():
    leader, market = _leader_rounds("HIT")
    full_market = []
    for i, row in enumerate(market):
        exit_price = 0.0105 if i < 5 else 0.0600
        full_market.extend([
            row,
            CopyabilitySwap(row.token_mint, "buy", 1.0, 100, 0.0100, 0.0, row.block_time + 10, "M"),
            CopyabilitySwap(row.token_mint, "sell", exit_price * 100, 100, exit_price, 0.0, row.block_time + 100, "M"),
        ])
    metrics = compute_copyability("W", leader, full_market, slippage=0.0, priority_fee_sol=0.0).as_metrics()
    assert metrics["copy_pnl_10s_sol"] > 0
    assert metrics["copyability_score"] < 90


def test_missing_price_data_returns_low_coverage_without_crash():
    leader, market = _leader_rounds("MISS", count=3)
    metrics = compute_copyability("W", leader, market, slippage=0.0, priority_fee_sol=0.0).as_metrics()
    assert metrics["copy_sample_size"] == 0
    assert metrics["copy_coverage_ratio"] == 0
    assert metrics["not_simulatable_count"] == 3


def test_negative_10s_copy_pnl_prevents_tracking_when_sample_sufficient():
    swaps = []
    for i in range(6):
        swaps.append(SwapEvent(f"M{i}", "buy", 1.0, 100, 0.0, i * 1000))
        swaps.append(SwapEvent(f"M{i}", "sell", 1.5, 100, 0.0, i * 1000 + 500))
    perf = compute_performance(swaps)
    metrics = {
        "copyability_score": 20,
        "copy_sample_size": 6,
        "copy_coverage_ratio": 1.0,
        "copy_pnl_10s_sol": -0.01,
        "copy_profit_factor_10s": 0.7,
        "avg_entry_jump_10s": 0.1,
    }
    result = score_wallet(perf, WalletSignals(history_days=10, days_since_last_trade=1), copyability_metrics=metrics)
    assert result.tracked is False
    assert any("10sn" in reason for reason in result.eligibility_failures)


def test_leaderboard_returns_copyability_metrics(db):
    db.add(Wallet(
        address="LeaderCopy111111111111111111111111111111",
        status=WalletStatus.tracked.value,
        latest_score=80,
        confidence=1.0,
        risk_flags=[],
        metrics={
            "copyability_score": 88,
            "copy_pnl_10s_sol": 0.1234,
            "copy_pnl_30s_sol": 0.1111,
            "avg_entry_jump_10s": 0.12,
            "copy_profit_factor_10s": 2.4,
            "copy_coverage_ratio": 0.9,
            "copy_sample_size": 9,
            "closed_positions": 9,
        },
    ))
    db.commit()
    rows = leaderboard(db=db)
    row = next(r for r in rows if r["address"].startswith("LeaderCopy"))
    assert row["copyability_score"] == 88
    assert row["copy_pnl_10s_sol"] == 0.1234


def test_frontend_podium_uses_closed_positions():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    page = (root / "frontend/app/wallets/leaderboard/page.tsx").read_text(encoding="utf-8")
    assert "closed_positions" in page
    assert "closed_trades ?? 0" not in page

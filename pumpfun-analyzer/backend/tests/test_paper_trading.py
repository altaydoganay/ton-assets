from app.trading.paper import PaperTradingEngine, CloseMode
from app.trading.risk import RiskConfig, DayState, evaluate_buy


def test_paper_buy_and_full_sell_profit():
    eng = PaperTradingEngine(slippage=0.0, priority_fee_sol=0.0)
    eng.buy("M", sol_amount=1.0, market_price_sol=0.01)  # 100 token
    pos = eng.positions["M"]
    assert round(pos.qty, 4) == 100
    fill = eng.sell_fraction("M", 1.0, market_price_sol=0.02)
    assert fill is not None
    assert round(fill.realized_pnl_sol, 4) == 1.0  # 100*0.02 - 1.0
    assert eng.positions["M"].is_open is False


def test_partial_sell_proportional():
    eng = PaperTradingEngine(slippage=0.0, priority_fee_sol=0.0, close_mode=CloseMode.PROPORTIONAL)
    eng.buy("M", 1.0, 0.01)  # 100 token, maliyet 1.0
    fill = eng.mirror_leader_sell("M", leader_sell_fraction=0.5, market_price_sol=0.02)
    assert fill is not None
    assert round(fill.token_amount, 4) == 50
    # pnl = 50*0.02 - 0.5 = 0.5
    assert round(fill.realized_pnl_sol, 4) == 0.5
    assert eng.positions["M"].is_open is True
    assert round(eng.positions["M"].qty, 4) == 50


def test_full_close_mode_ignores_fraction():
    eng = PaperTradingEngine(slippage=0.0, priority_fee_sol=0.0, close_mode=CloseMode.FULL)
    eng.buy("M", 1.0, 0.01)
    fill = eng.mirror_leader_sell("M", leader_sell_fraction=0.3, market_price_sol=0.02)
    assert fill is not None
    assert eng.positions["M"].is_open is False  # tamamı kapandı


def test_slippage_reduces_proceeds():
    eng = PaperTradingEngine(slippage=0.1, priority_fee_sol=0.0)
    eng.buy("M", 1.0, 0.01)
    qty = eng.positions["M"].qty
    # alış slippage'ı: exec 0.011 => qty = 1/0.011
    assert round(qty, 2) == round(1 / 0.011, 2)


def test_risk_blocks_when_disabled():
    cfg = RiskConfig(enabled=False)
    dec = evaluate_buy(cfg, DayState(), wallet_address="W", token_mint="T",
                       wallet_score=90, token_score=90, token_liquidity_sol=100,
                       token_sellable=True, follow_lag_seconds=5)
    assert dec.allowed is False


def test_risk_allows_when_paper_enabled():
    cfg = RiskConfig(enabled=True, mode="paper", min_liquidity_sol=5)
    dec = evaluate_buy(cfg, DayState(), wallet_address="W", token_mint="T",
                       wallet_score=90, token_score=90, token_liquidity_sol=100,
                       token_sellable=True, follow_lag_seconds=5)
    assert dec.allowed is True
    assert dec.sol_amount == cfg.fixed_sol_amount


def test_risk_daily_spend_limit():
    cfg = RiskConfig(enabled=True, mode="paper", fixed_sol_amount=1.0, max_position_sol=1.0, max_daily_spend_sol=1.5)
    day = DayState(spent_sol=1.0)
    dec = evaluate_buy(cfg, day, wallet_address="W", token_mint="T",
                       wallet_score=90, token_score=90, token_liquidity_sol=100,
                       token_sellable=True, follow_lag_seconds=5)
    assert dec.allowed is False
    assert any("harcama" in r for r in dec.reasons)


def test_risk_live_requires_confirmation():
    cfg = RiskConfig(enabled=True, mode="live", live_confirmed=False)
    dec = evaluate_buy(cfg, DayState(), wallet_address="W", token_mint="T",
                       wallet_score=90, token_score=90, token_liquidity_sol=100,
                       token_sellable=True, follow_lag_seconds=5)
    assert dec.allowed is False


def test_emergency_stop_blocks():
    cfg = RiskConfig(enabled=True, mode="paper", emergency_stop=True)
    dec = evaluate_buy(cfg, DayState(), wallet_address="W", token_mint="T",
                       wallet_score=90, token_score=90, token_liquidity_sol=100,
                       token_sellable=True, follow_lag_seconds=5)
    assert dec.allowed is False

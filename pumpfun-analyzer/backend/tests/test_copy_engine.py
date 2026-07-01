from app.trading.engine import CopyTradeEngine, TradeContext, LiveTradingNotConfigured
from app.trading.risk import RiskConfig
from app.models import PaperTrade
import pytest


def _ctx(**kw):
    base = dict(
        wallet_address="Lead111", token_mint="Tok111", wallet_score=85, token_score=80,
        token_liquidity_sol=50, token_sellable=True, follow_lag_seconds=5,
        market_price_sol=0.01, leader_sol_amount=1.0, source_signature="srcsig1",
    )
    base.update(kw)
    return TradeContext(**base)


def test_paper_buy_persisted(db):
    cfg = RiskConfig(enabled=True, mode="paper", paper_trade_sol=0.1, min_liquidity_sol=5)
    eng = CopyTradeEngine(cfg)
    dec = eng.on_leader_buy(db, _ctx())
    assert dec.allowed is True
    row = db.query(PaperTrade).filter(PaperTrade.source_signature == "srcsig1", PaperTrade.side == "buy").first()
    assert row is not None
    assert row.sol_amount == 0.1


def test_safety_recheck_blocks_unsellable(db):
    cfg = RiskConfig(enabled=True, mode="paper", min_liquidity_sol=5)
    eng = CopyTradeEngine(cfg)
    # risk geçer ama son kontrolde sellable False olduğundan engellenmeli
    dec = eng.on_leader_buy(db, _ctx(token_sellable=False))
    assert dec.allowed is False
    assert any("satılabilir" in r for r in dec.reasons)


def test_mirror_partial_sell(db):
    cfg = RiskConfig(enabled=True, mode="paper", fixed_sol_amount=1.0, max_position_sol=1.0, min_liquidity_sol=5)
    eng = CopyTradeEngine(cfg)
    eng.on_leader_buy(db, _ctx())
    sell = eng.on_leader_sell(db, _ctx(market_price_sol=0.02), leader_sell_fraction=0.5)
    assert sell is not None
    assert sell.side == "sell"
    # pozisyon kısmen açık kalmalı
    assert eng.paper.positions["Tok111"].is_open is True


def test_live_requires_signer(db):
    cfg = RiskConfig(enabled=True, mode="live", live_confirmed=True, min_liquidity_sol=5)
    eng = CopyTradeEngine(cfg, signer=None)
    with pytest.raises(LiveTradingNotConfigured):
        eng.on_leader_buy(db, _ctx())

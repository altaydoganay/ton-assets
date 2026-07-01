"""Açık pozisyonlarda CANLI gerçekleşmemiş PnL (anlık fiyatla)."""
from app.adapters.base import MarketProvider, TokenMarketData
from app.models import PaperTrade
from app.services.stats_service import open_positions

MINT = "LivePosMint1111111111111111111111111111111"


class FixedMarket(MarketProvider):
    name = "fixed"
    def __init__(self, price, price_usd=None, liquidity_usd=None):
        self.price = price; self.price_usd = price_usd; self.liquidity_usd = liquidity_usd
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=True, price_sol=self.price,
                               price_usd=self.price_usd, liquidity_usd=self.liquidity_usd)


def _buy(db, qty, cost, price):
    db.add(PaperTrade(wallet_address="W", token_mint=MINT, side="buy", sol_amount=cost,
                      token_amount=qty, price_sol=price, fee_sol=0.0, is_open=True,
                      reason="copy-buy (paper)"))
    db.commit()


def test_open_position_live_profit(db):
    db.query(PaperTrade).delete(); db.commit()
    _buy(db, qty=100, cost=0.10, price=0.001)   # ort maliyet 0.001/birim
    rows = open_positions(db, market=FixedMarket(0.002))  # fiyat 2x
    assert len(rows) == 1
    p = rows[0]
    # değer = 100*0.002 = 0.20; PnL = 0.20 - 0.10 = +0.10; % = +100
    assert abs(p["current_value_sol"] - 0.20) < 1e-6
    assert abs(p["unrealized_pnl_sol"] - 0.10) < 1e-6
    assert abs(p["unrealized_pnl_pct"] - 1.0) < 1e-6


def test_open_position_live_loss(db):
    db.query(PaperTrade).delete(); db.commit()
    _buy(db, qty=100, cost=0.10, price=0.001)
    rows = open_positions(db, market=FixedMarket(0.0005))  # fiyat yarıya
    p = rows[0]
    assert abs(p["unrealized_pnl_sol"] - (-0.05)) < 1e-6
    assert abs(p["unrealized_pnl_pct"] - (-0.5)) < 1e-6


def test_open_position_value_capped_by_liquidity(db):
    """Bozuk giriş (imkânsız miktar) => değer havuz likiditesini aşamaz; suspicious."""
    db.query(PaperTrade).delete(); db.commit()
    # 0.01 SOL ile sözde 2.4 MİLYAR token "alınmış" (parse glitch)
    _buy(db, qty=2_400_000_000, cost=0.01, price=4e-12)
    # güncel: fiyat 5.25e-8 SOL, SOL=$150 => price_usd ~7.87e-6, likidite ~13 SOL
    rows = open_positions(db, market=FixedMarket(5.25e-8, price_usd=7.87e-6, liquidity_usd=2000.0))
    p = rows[0]
    assert p["suspicious"] is True
    # ham değer ~126 SOL olurdu; likidite tavanıyla ~13 SOL'a sınırlanır (<< ham)
    assert p["current_value_sol"] < 20
    # likidite_sol = 2000 / (7.87e-6/5.25e-8) = 2000/149.9 ≈ 13.3
    assert abs(p["current_value_sol"] - 13.34) < 0.5


def test_open_position_no_price_is_none(db):
    db.query(PaperTrade).delete(); db.commit()
    _buy(db, qty=100, cost=0.10, price=0.001)
    rows = open_positions(db, market=None)  # canlı fiyat yok, cache de yok
    p = rows[0]
    assert p["unrealized_pnl_sol"] is None
    assert p["unrealized_pnl_pct"] is None
    assert p["cost_sol"] == 0.1

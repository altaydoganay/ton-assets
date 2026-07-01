"""Worker yeniden başlama dayanıklılığı: CopyTradeEngine.hydrate_from_db.

Restart sonrası bellek-içi durum kaybolur; bu, (1) açık paper pozisyonlarını
DB'den geri kurmalı (lider satınca yansıtma çalışsın, yetim pozisyon olmasın) ve
(2) bugünkü harcama/zarar sayaçlarını (günlük devre kesici) geri doldurmalı.
"""
from datetime import datetime, timezone

from app.models import PaperTrade
from app.trading.engine import CopyTradeEngine
from app.trading.risk import RiskConfig


def _buy(mint, sol, qty, sig):
    return PaperTrade(wallet_address="W", token_mint=mint, side="buy", sol_amount=sol,
                      token_amount=qty, price_sol=sol / qty, fee_sol=0.0, is_open=True,
                      reason="copy-buy (paper)", source_signature=sig,
                      created_at=datetime.now(timezone.utc))


def _sell(mint, sol, qty, pnl, sig):
    return PaperTrade(wallet_address="W", token_mint=mint, side="sell", sol_amount=sol,
                      token_amount=qty, price_sol=sol / qty, fee_sol=0.0, is_open=False,
                      realized_pnl_sol=pnl, reason="mirror-sell (paper)", source_signature=sig,
                      created_at=datetime.now(timezone.utc))


def test_hydrate_recovers_open_position(db):
    db.query(PaperTrade).delete(); db.commit()
    mint = "RecoverMint1111111111111111111111111111111"
    db.add(_buy(mint, 0.10, 100.0, "rb1")); db.commit()

    eng = CopyTradeEngine(RiskConfig(enabled=True, mode="paper"))
    stats = eng.hydrate_from_db(db)

    assert stats["recovered_positions"] == 1
    pos = eng.paper.positions[mint]
    assert abs(pos.qty - 100.0) < 1e-9
    assert abs(pos.cost_sol - 0.10) < 1e-9
    # açık pozisyon devre-kesici durumuna da yazılmalı (token başına limit)
    assert eng.day.open_positions.get(mint) == 1


def test_hydrate_partial_sell_leaves_remaining(db):
    db.query(PaperTrade).delete(); db.commit()
    mint = "RecoverMint2222222222222222222222222222222"
    db.add(_buy(mint, 0.10, 100.0, "rb2"))
    db.add(_sell(mint, 0.06, 40.0, 0.02, "rs2"))  # 40/100 satıldı
    db.commit()

    eng = CopyTradeEngine(RiskConfig(enabled=True, mode="paper"))
    eng.hydrate_from_db(db)

    pos = eng.paper.positions[mint]
    assert abs(pos.qty - 60.0) < 1e-9              # 100 - 40 kaldı
    assert abs(pos.cost_sol - 0.06) < 1e-9          # ortalama-maliyet: 0.10 * 60/100


def test_hydrate_fully_closed_not_recovered(db):
    db.query(PaperTrade).delete(); db.commit()
    mint = "RecoverMint3333333333333333333333333333333"
    db.add(_buy(mint, 0.10, 100.0, "rb3"))
    db.add(_sell(mint, 0.08, 100.0, -0.02, "rs3"))  # tamamı kapandı, zarar
    db.commit()

    eng = CopyTradeEngine(RiskConfig(enabled=True, mode="paper"))
    stats = eng.hydrate_from_db(db)

    assert stats["recovered_positions"] == 0
    assert mint not in eng.paper.positions or not eng.paper.positions[mint].is_open
    # bugünkü zarar devre-kesici sayacına yansımalı
    assert abs(eng.day.loss_sol - 0.02) < 1e-9

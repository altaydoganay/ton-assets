"""Akıllı çıkış motoru: takip eden stop + zaman çıkışı + öncelikler."""
from app.adapters.base import MarketProvider, TokenMarketData
from app.models import PaperTrade
from app.services.position_manager import _decide, manage_positions
from app.services.settings_service import seed_defaults, set_setting, DEFAULTS


def _d(**kw):
    base = dict(pnl_pct=0.0, peak_pnl_pct=0.0, drop_from_peak=0.0, held_min=0.0,
               tp=0.5, sl=0.25, trail=0.12, trail_act=0.15, max_hold_min=45)
    base.update(kw)
    return _decide(**base)


def test_decide_priorities():
    assert _d(pnl_pct=-0.30) == "sl"                       # sert SL en önce
    assert _d(pnl_pct=0.6) == "tp"                          # sert TP
    assert _d(peak_pnl_pct=0.20, drop_from_peak=0.15) == "trailing"  # zirveden düşüş
    assert _d(held_min=50) == "time"                       # zaman çıkışı
    # takip eden stop AKTİF DEĞİL (zirve kârı < aktivasyon) => çıkış yok
    assert _d(tp=0, sl=0, max_hold_min=0, peak_pnl_pct=0.10, drop_from_peak=0.20) is None
    # hiçbiri tetiklenmez
    assert _d(pnl_pct=0.05, peak_pnl_pct=0.10, drop_from_peak=0.02, held_min=5) is None


class MutableMarket(MarketProvider):
    name = "mut"
    def __init__(self, price): self.price = price
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=True, price_sol=self.price)


def test_trailing_stop_locks_profit(db):
    seed_defaults(db)
    db.query(PaperTrade).delete()
    set_setting(db, "position_state", {})
    # +%50 TP'ye değmesin diye TP/SL kapalı; sadece trailing
    set_setting(db, "risk", {**DEFAULTS["risk"], "pure_mirror_mode": False, "take_profit_pct": 0.0, "stop_loss_pct": 0.0,
                             "trailing_stop_pct": 0.12, "trail_activate_pct": 0.15, "max_hold_minutes": 0})
    # alım: 100 token, 1.0 SOL maliyet => avg 0.01
    db.add(PaperTrade(wallet_address="W", token_mint="TRAIL", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.commit()

    # 1. döngü: fiyat 0.013 (+%30) => zirve kaydedilir, düşüş yok => çıkış yok
    assert manage_positions(db, MutableMarket(0.013)) == []
    # 2. döngü: fiyat 0.0113 => zirveden (0.013) ~%13 düşüş >= %12 => trailing çıkış
    closed = manage_positions(db, MutableMarket(0.0113))
    assert len(closed) == 1 and closed[0]["reason"] == "trailing"
    assert db.query(PaperTrade).filter(PaperTrade.token_mint == "TRAIL", PaperTrade.side == "sell").count() == 1


def test_no_exit_when_all_disabled(db):
    seed_defaults(db)
    db.query(PaperTrade).delete()
    set_setting(db, "risk", {**DEFAULTS["risk"], "pure_mirror_mode": False, "take_profit_pct": 0.0, "stop_loss_pct": 0.0,
                             "trailing_stop_pct": 0.0, "max_hold_minutes": 0})
    db.add(PaperTrade(wallet_address="W", token_mint="NOEX", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.commit()
    assert manage_positions(db, MutableMarket(0.05)) == []

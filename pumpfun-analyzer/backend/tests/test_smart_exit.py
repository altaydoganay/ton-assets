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
                             "trailing_stop_pct": 0.0, "max_hold_minutes": 0,
                             "partial_tp_pct": 0.0, "exit_liq_drop_pct": 0.0, "stagnant_exit_minutes": 0})
    db.add(PaperTrade(wallet_address="W", token_mint="NOEX", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.commit()
    assert manage_positions(db, MutableMarket(0.05)) == []


# --- Yeni akıllı çıkış paketi: kademeli TP + likidite watchdog + durgunluk ---
from datetime import datetime, timezone, timedelta

SMART_MINT = "SmartExitMint111111111111111111111111111111"


class LiqMarket(MarketProvider):
    name = "liq"
    def __init__(self, price, liq_usd=None):
        self.price = price; self.liq_usd = liq_usd
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=True,
                               price_sol=self.price, liquidity_usd=self.liq_usd)


def _smart_risk(db, **over):
    base = {**DEFAULTS["risk"], "pure_mirror_mode": False, "strategy_mode": "copy",
            "take_profit_pct": 0, "stop_loss_pct": 0, "trailing_stop_pct": 0,
            "max_hold_minutes": 0, "partial_tp_pct": 0, "partial_tp_fraction": 0.5,
            "exit_liq_drop_pct": 0, "stagnant_exit_minutes": 0, "stagnant_max_pnl_pct": 0.0}
    base.update(over)
    set_setting(db, "risk", base)


def _smart_open(db, qty=100.0, cost=0.10, minutes_ago=1):
    db.query(PaperTrade).delete(); db.commit()
    set_setting(db, "position_state", {})
    t = PaperTrade(wallet_address="W", token_mint=SMART_MINT, side="buy", sol_amount=cost,
                   token_amount=qty, price_sol=cost / qty, fee_sol=0.0, is_open=True,
                   reason="copy-buy (paper)")
    db.add(t); db.commit()
    t.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db.commit()


def test_partial_tp_sells_fraction_keeps_rest_open(db):
    _smart_risk(db, partial_tp_pct=0.30, partial_tp_fraction=0.5)
    _smart_open(db, qty=100, cost=0.10)  # giriş 0.001/adet
    out = manage_positions(db, LiqMarket(0.0015))  # +%50 → kademeli tetiklenir
    assert [c["reason"] for c in out] == ["partial_tp"]
    sells = db.query(PaperTrade).filter(PaperTrade.side == "sell").all()
    assert len(sells) == 1 and abs(sells[0].token_amount - 50.0) < 1e-6
    assert sells[0].realized_pnl_sol > 0
    # ikinci turda TEKRAR kademeli satmaz (bir kez)
    out2 = manage_positions(db, LiqMarket(0.0015))
    assert all(c["reason"] != "partial_tp" for c in out2)


def test_liquidity_pull_forces_full_exit(db):
    _smart_risk(db, exit_liq_drop_pct=0.6)
    _smart_open(db, qty=100, cost=0.10)
    manage_positions(db, LiqMarket(0.001, liq_usd=5000.0))       # zirve likidite
    out = manage_positions(db, LiqMarket(0.0009, liq_usd=1200.0))  # %76 düşüş → acil
    assert [c["reason"] for c in out] == ["liq_pull"]
    sells = db.query(PaperTrade).filter(PaperTrade.side == "sell").all()
    assert len(sells) == 1 and abs(sells[0].token_amount - 100.0) < 1e-6


def test_liquidity_small_pool_noise_ignored(db):
    _smart_risk(db, exit_liq_drop_pct=0.6)
    _smart_open(db, qty=100, cost=0.10)
    manage_positions(db, LiqMarket(0.001, liq_usd=300.0))  # 500$ tabanın altı
    assert manage_positions(db, LiqMarket(0.001, liq_usd=50.0)) == []


def test_stagnant_exit_after_minutes_without_profit(db):
    _smart_risk(db, stagnant_exit_minutes=10, stagnant_max_pnl_pct=0.0)
    _smart_open(db, qty=100, cost=0.10, minutes_ago=15)  # 15 dk'dır kârsız
    out = manage_positions(db, LiqMarket(0.00095))
    assert [c["reason"] for c in out] == ["stagnant"]


def test_stagnant_not_triggered_when_profitable(db):
    _smart_risk(db, stagnant_exit_minutes=10)
    _smart_open(db, qty=100, cost=0.10, minutes_ago=15)
    assert manage_positions(db, LiqMarket(0.002)) == []  # +%100 → durgun değil

from app.trading.risk import tp_sl_should_close
from app.services.position_manager import manage_positions
from app.services.settings_service import seed_defaults, set_setting, DEFAULTS
from app.services.stats_service import open_positions
from app.adapters.base import MarketProvider, TokenMarketData
from app.models import PaperTrade, Alert


def _reset_trades(db):
    db.query(PaperTrade).delete()
    db.commit()


def test_tp_sl_decision():
    assert tp_sl_should_close(1.0, 100, 0.015, take_profit_pct=0.5, stop_loss_pct=0.3) == "tp"
    assert tp_sl_should_close(1.0, 100, 0.006, take_profit_pct=0.5, stop_loss_pct=0.3) == "sl"
    assert tp_sl_should_close(1.0, 100, 0.011, take_profit_pct=0.5, stop_loss_pct=0.3) is None
    assert tp_sl_should_close(1.0, 100, 0.02, 0, 0) is None


class FixedMarket(MarketProvider):
    name = "fixed"
    def __init__(self, price): self.price = price
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, price_sol=self.price, ok=True)


def test_manage_positions_closes_on_tp(db):
    seed_defaults(db); _reset_trades(db)
    db.add(PaperTrade(wallet_address="W", token_mint="TPMINT", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.commit()
    set_setting(db, "risk", {**DEFAULTS["risk"], "pure_mirror_mode": False, "take_profit_pct": 0.5, "stop_loss_pct": 0.3})
    closed = manage_positions(db, FixedMarket(0.02))  # +%100 => TP
    assert len(closed) == 1 and closed[0]["reason"] == "tp"
    assert all(p["token_mint"] != "TPMINT" for p in open_positions(db))


def test_manage_positions_noop_when_disabled(db):
    seed_defaults(db); _reset_trades(db)
    set_setting(db, "risk", {**DEFAULTS["risk"], "take_profit_pct": 0.0, "stop_loss_pct": 0.0})
    db.add(PaperTrade(wallet_address="W", token_mint="NOTP", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.commit()
    assert manage_positions(db, FixedMarket(0.05)) == []


def test_resend_alert(db):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    a = Alert(dedup_key="rs:1", signature="rs1", wallet_address="W", token_mint="T",
              payload={"message": "test mesaj"}, sent=False)
    db.add(a); db.commit(); db.refresh(a)
    r = client.post(f"/api/alerts/{a.id}/resend")
    assert r.status_code == 200 and "sent" in r.json()
    assert client.post("/api/alerts/999999/resend").status_code == 404


def test_tracked_hysteresis(db):
    """Takipteki cüzdan 65-70 bandında takipte kalır, 65 altında düşer."""
    from app.models import Wallet, WalletStatus
    from app.core.scoring.wallet_scoring import WalletScoreResult
    from app.services.analysis_service import persist_wallet_score

    def _res(total, eligible=True):
        return WalletScoreResult(
            total=total, performance=total, consistency=total, risk=total, organic=total,
            hold_quality=total, safety=total, recency=total, breakdown={}, vetoed=False,
            veto_reasons=[], eligible=eligible, eligibility_failures=[], confidence=0.9,
            tracked=(eligible and total >= 70),
        )

    w = Wallet(address="HystW1", status=WalletStatus.tracked.value, latest_score=72)
    db.add(w); db.commit()
    # 67 (eligible, <70 ama >=65) => takipte kalmalı (histerezis)
    persist_wallet_score(db, w, _res(67), demote_below=65)
    db.refresh(w)
    assert w.status == WalletStatus.tracked.value
    # 63 (<65) => eşik altına düşer
    persist_wallet_score(db, w, _res(63), demote_below=65)
    db.refresh(w)
    assert w.status == WalletStatus.below_threshold.value

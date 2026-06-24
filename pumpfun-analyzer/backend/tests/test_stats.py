from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, LiveTrade, PaperTrade, Wallet, WalletStatus, Token, TokenStatus
from app.services import stats_service
from app.services.settings_service import seed_defaults, get_setting

client = TestClient(app)


def _clean(db):
    """Stats testleri toplam (aggregate) hesapladığı için izole bir DB gerekir."""
    for model in (PaperTrade, LiveTrade, Alert, Token, Wallet):
        db.query(model).delete()
    db.commit()


def _seed(db):
    db.add(Wallet(address="W_track_1", status=WalletStatus.tracked.value, latest_score=80))
    db.add(Wallet(address="W_disc_1", status=WalletStatus.discovered.value))
    db.add(Wallet(address="W_rej_1", status=WalletStatus.rejected.value, latest_score=40))
    db.add(Token(mint="T_track_1", status=TokenStatus.tracked.value, latest_score=75,
                 metrics={"price_sol": 0.02}))
    db.add(PaperTrade(wallet_address="W_track_1", token_mint="T_track_1", side="buy",
                      sol_amount=1.0, token_amount=100, price_sol=0.01))
    db.add(PaperTrade(wallet_address="W_track_1", token_mint="T_track_1", side="sell",
                      sol_amount=1.4, token_amount=100, price_sol=0.014, realized_pnl_sol=0.4))
    db.add(PaperTrade(wallet_address="W_track_1", token_mint="OPEN_MINT", side="buy",
                      sol_amount=0.5, token_amount=50, price_sol=0.01))
    db.commit()


def test_overview(db):
    seed_defaults(db); _clean(db); _seed(db)
    b = client.get("/api/stats/overview").json()
    assert b["wallets"]["tracked"] == 1
    assert b["tokens"]["tracked"] == 1
    assert round(b["pnl"]["paper_sol"], 2) == 0.4


def test_performance(db):
    seed_defaults(db); _clean(db); _seed(db)
    b = client.get("/api/stats/performance").json()
    assert b["closed_trades"] == 1
    assert b["win_rate"] == 1.0
    assert len(b["curve"]) == 1


def test_open_positions_derived(db):
    seed_defaults(db); _clean(db); _seed(db)
    pos = stats_service.open_positions(db)
    mints = [p["token_mint"] for p in pos]
    assert "OPEN_MINT" in mints
    assert "T_track_1" not in mints


def test_setup_status(db):
    seed_defaults(db)
    b = client.get("/api/setup").json()
    assert "checks" in b and len(b["checks"]) >= 5


def test_apply_risk_profile(db):
    seed_defaults(db)
    assert client.post("/api/setup/risk-profiles/agresif").status_code == 200
    assert get_setting(db, "risk")["min_wallet_score"] == 65
    assert client.post("/api/setup/risk-profiles/yokboyle").status_code == 404


def test_manual_close_position(db):
    seed_defaults(db); _clean(db); _seed(db)
    r = client.post("/api/stats/positions/OPEN_MINT/close?price_sol=0.02")
    assert r.status_code == 200
    assert "OPEN_MINT" not in [p["token_mint"] for p in stats_service.open_positions(db)]


def test_export_wallets_csv(db):
    seed_defaults(db); _clean(db); _seed(db)
    r = client.get("/api/export/wallets.csv")
    assert r.status_code == 200 and "W_track_1" in r.text

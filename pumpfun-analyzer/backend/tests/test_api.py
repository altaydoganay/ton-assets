from fastapi.testclient import TestClient

from app.main import app
from app.services.settings_service import seed_defaults
from app.core.analysis.pnl import compute_performance, SwapEvent
from app.core.scoring.wallet_scoring import WalletSignals, score_wallet
from app.services.analysis_service import get_or_create_wallet, persist_wallet_score

client = TestClient(app)


def test_health(db):
    seed_defaults(db)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True
    assert body["trading_mode"] in ("paper", "alerts_only", "live")


def test_settings_roundtrip(db):
    seed_defaults(db)
    r = client.get("/api/settings/thresholds")
    assert r.status_code == 200
    assert r.json()["value"]["wallet"] == 55.0  # v8: geniş ağ (eşik 55) + otomatik eleme

    r = client.put("/api/settings/thresholds", json={"value": {"wallet": 75.0, "token": 72.0}})
    assert r.status_code == 200
    assert r.json()["value"]["wallet"] == 75.0


def test_unknown_setting_404(db):
    r = client.get("/api/settings/does-not-exist")
    assert r.status_code == 404


def test_wallet_flow(db):
    # Cüzdan oluştur + puanla + API'den oku
    swaps = []
    t = 0
    for i in range(12):          # 12 token, her birinde 2 tur => 24 kapalı pozisyon
        m = f"MINT{i}"
        for _ in range(2):
            swaps += [
                SwapEvent(m, "buy", 1.0, 100, 0.01, t),
                SwapEvent(m, "sell", 1.4, 100, 0.01, t + 3600),
            ]
            t += 7200
    perf = compute_performance(swaps)
    sig = WalletSignals(history_days=45, days_since_last_trade=1)
    res = score_wallet(perf, sig)
    w = get_or_create_wallet(db, "ApiWalletAddr1111111111111111111111111111111")
    persist_wallet_score(db, w, res, metrics={"swaps": len(swaps)})

    r = client.get("/api/wallets/tracked")
    assert r.status_code == 200
    addrs = [x["address"] for x in r.json()]
    assert "ApiWalletAddr1111111111111111111111111111111" in addrs

    r = client.get("/api/wallets/ApiWalletAddr1111111111111111111111111111111/score-history")
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert r.json()[0]["total"] >= 70


def test_wallet_404(db):
    r = client.get("/api/wallets/yokboyle")
    assert r.status_code == 404


def test_add_wallet_endpoint(db, monkeypatch):
    # Zincir sağlayıcıyı sahte (boş) bir provider ile değiştir — ağ gerekmez.
    from app.adapters.base import ChainProvider

    class EmptyProvider(ChainProvider):
        name = "empty"
        def get_signatures_for_address(self, address, limit=100): return []
        def get_transaction(self, signature): return None
        def get_token_supply(self, mint): return None
        def get_mint_info(self, mint): return None

    import app.api.routes_wallets as rw
    monkeypatch.setattr(rw, "build_chain_provider", lambda: EmptyProvider())

    r = client.post("/api/wallets", json={"address": "AddedWallet11111111111111111111111111111111", "limit": 10})
    assert r.status_code == 201
    body = r.json()
    assert body["address"] == "AddedWallet11111111111111111111111111111111"
    assert "latest_score" in body  # puanlandı (örneklem yok => düşük/ineligible)

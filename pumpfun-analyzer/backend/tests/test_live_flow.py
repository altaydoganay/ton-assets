import time
import pytest

from app.adapters.base import ChainProvider, MarketProvider, TokenMarketData
from app.adapters.pumpportal import PumpPortalTrade
from app.models import Wallet, WalletStatus, PaperTrade, Alert
from app.notifications.telegram import TelegramNotifier
from app.services.live_flow import handle_trade_event, reset_engine
from app.services.settings_service import set_setting


class FakeChain(ChainProvider):
    name = "fake"

    def __init__(self, mint_auth=None, freeze_auth=None, top_amounts=None, supply=1_000_000):
        self.mint_auth = mint_auth
        self.freeze_auth = freeze_auth
        self.top_amounts = top_amounts or [50000, 40000, 30000, 20000, 10000]
        self.supply = supply

    def get_signatures_for_address(self, address, limit=100):
        return []

    def get_transaction(self, signature):
        return None

    def get_token_supply(self, mint):
        return {"value": {"uiAmount": self.supply}}

    def get_mint_info(self, mint):
        return {"mintAuthority": self.mint_auth, "freezeAuthority": self.freeze_auth}

    def get_token_largest_accounts(self, mint):
        return [{"uiAmount": a} for a in self.top_amounts]


class FakeMarket(MarketProvider):
    name = "fake"

    def __init__(self, ok=True, liq_usd=240000.0):
        self.ok = ok
        self.liq_usd = liq_usd

    def get_token_market(self, mint):
        if not self.ok:
            return TokenMarketData(mint=mint, source=self.name, ok=False)
        return TokenMarketData(
            mint=mint, price_usd=0.002, price_sol=0.00001,  # sol_usd = 200
            liquidity_usd=self.liq_usd, market_cap_usd=500000, fdv_usd=600000,
            volume_24h_usd=200000, pair_created_at=int((time.time() - 86400) * 1000),
            source=self.name, ok=True,
        )


def _make_tracked_wallet(db, addr="LeaderWallet1111111111111111111111111111111"):
    w = Wallet(address=addr, status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _trade(addr, mint="HealthyMint11111111111111111111111111111111", side="buy", sig="evt1"):
    return PumpPortalTrade(signature=sig, trader=addr, mint=mint, side=side,
                           sol_amount=1.0, token_amount=20000, pool="pumpswap",
                           market_cap_sol=100, raw={})


@pytest.fixture(autouse=True)
def _reset():
    reset_engine()
    yield
    reset_engine()


def test_ignored_when_wallet_not_tracked(db):
    res = handle_trade_event(db, _trade("UnknownWallet999"), chain=FakeChain(), market=FakeMarket(),
                             notifier=TelegramNotifier())
    assert res["action"] == "ignored"


def test_buy_creates_alert_and_paper_trade(db):
    w = _make_tracked_wallet(db)
    # paper modu aç
    set_setting(db, "risk", {"enabled": True, "mode": "paper", "fixed_sol_amount": 0.1,
                             "max_position_sol": 0.5, "min_liquidity_sol": 5,
                             "min_wallet_score": 70, "min_token_score": 70})
    reset_engine()
    res = handle_trade_event(db, _trade(w.address, sig="buyevt"), chain=FakeChain(), market=FakeMarket(),
                             notifier=TelegramNotifier())
    assert res["action"] == "buy"
    assert res["token_ok"] is True
    assert res["alerted"] is True
    assert res["traded"] is True
    assert db.query(Alert).filter(Alert.signature == "buyevt").count() == 1
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "buyevt", PaperTrade.side == "buy").count() == 1


def test_buy_dedup_no_duplicate_alert(db):
    w = _make_tracked_wallet(db, addr="Leader222222222222222222222222222222222222")
    handle_trade_event(db, _trade(w.address, sig="dup1"), chain=FakeChain(), market=FakeMarket(), notifier=TelegramNotifier())
    handle_trade_event(db, _trade(w.address, sig="dup1"), chain=FakeChain(), market=FakeMarket(), notifier=TelegramNotifier())
    assert db.query(Alert).filter(Alert.signature == "dup1").count() == 1


def test_token_vetoed_skips_alert(db):
    w = _make_tracked_wallet(db, addr="Leader333333333333333333333333333333333333")
    # mint authority aktif => kritik veto
    res = handle_trade_event(db, _trade(w.address, mint="DangerMint", sig="vetoevt"),
                             chain=FakeChain(mint_auth="SomeAuthority"), market=FakeMarket(),
                             notifier=TelegramNotifier())
    assert res["action"] == "skipped"
    assert db.query(Alert).filter(Alert.signature == "vetoevt").count() == 0


def test_live_mode_uses_signer(db):
    w = _make_tracked_wallet(db, addr="Leader444444444444444444444444444444444444")
    set_setting(db, "risk", {"enabled": True, "mode": "live", "live_confirmed": True,
                             "fixed_sol_amount": 0.05, "max_position_sol": 0.5,
                             "min_liquidity_sol": 5, "min_wallet_score": 70, "min_token_score": 70})
    reset_engine()

    class FakeSigner:
        def __init__(self): self.calls = []
        def submit_buy(self, mint, amt, price, max_slippage=0.15, priority_fee_sol=0.0005):
            self.calls.append((mint, amt)); return "livesig1"

    signer = FakeSigner()
    res = handle_trade_event(db, _trade(w.address, sig="liveevt"), chain=FakeChain(), market=FakeMarket(),
                             notifier=TelegramNotifier(), signer=signer)
    assert res["action"] == "buy"
    assert res["traded"] is True
    assert len(signer.calls) == 1
    from app.models import LiveTrade
    lt = db.query(LiveTrade).filter(LiveTrade.source_signature == "liveevt").first()
    assert lt is not None and lt.signature == "livesig1" and lt.status == "submitted"

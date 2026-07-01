import time
import pytest

from app.adapters.base import ChainProvider, MarketProvider, TokenMarketData
from app.adapters.pumpportal import PumpPortalTrade
from app.models import Wallet, WalletStatus, PaperTrade, LiveTrade, Alert
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
    # Build 73: canlı kopya için lider cüzdanın DOĞRULANMIŞ copyability'si gerekir
    # (örneklem >= 12, pozitif 10sn copy PnL, skor >= 65). Testlerdeki lider
    # bunları karşılamalı ki canlı güvenlik kapısı signer yolunu engellemesin.
    w = Wallet(address=addr, status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[],
               metrics={"copy_sample_size": 20, "copy_pnl_10s_sol": 0.12, "copyability_score": 78,
                        "copy_profit_factor_10s": 2.0, "copy_coverage_ratio": 0.9, "avg_entry_jump_10s": 0.05})
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _trade(addr, mint="HealthyMint11111111111111111111111111111111", side="buy", sig="evt1"):
    return PumpPortalTrade(signature=sig, trader=addr, mint=mint, side=side,
                           sol_amount=1.0, token_amount=20000, pool="pumpswap",
                           market_cap_sol=100, raw={})


@pytest.fixture(autouse=True)
def _reset(db):
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
    reset_engine()
    yield
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
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
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
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


def test_token_assessment_cached_second_time(db):
    w = _make_tracked_wallet(db, addr="Leader555555555555555555555555555555555555")

    class CountingChain(FakeChain):
        def __init__(self): super().__init__(); self.mint_calls = 0
        def get_mint_info(self, mint):
            self.mint_calls += 1
            return super().get_mint_info(mint)

    chain = CountingChain()
    umint = "CacheUniqueMint1111111111111111111111111111"
    r1 = handle_trade_event(db, _trade(w.address, mint=umint, sig="c1"), chain=chain, market=FakeMarket(), notifier=TelegramNotifier())
    r2 = handle_trade_event(db, _trade(w.address, mint=umint, sig="c2"), chain=chain, market=FakeMarket(), notifier=TelegramNotifier())
    assert r1["cached"] is False     # ilk seferde analiz edildi
    assert r2["cached"] is True      # ikinci seferde önbellekten (anında)
    assert chain.mint_calls == 1     # token ikinci kez zincire sorulmadı


def test_live_mode_uses_signer(db):
    w = _make_tracked_wallet(db, addr="Leader444444444444444444444444444444444444")
    set_setting(db, "risk", {"enabled": True, "mode": "live", "live_confirmed": True,
                             "fixed_sol_amount": 0.05, "max_position_sol": 0.5,
                             "min_liquidity_sol": 5, "min_wallet_score": 70, "min_token_score": 70,
                             "live_require_known_token_age": False, "live_min_token_age_seconds": 0,
                             "live_max_token_age_minutes": 0})
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
    reset_engine()

    class FakeSigner:
        def __init__(self): self.calls = []
        def submit_buy(self, mint, amt, price, max_slippage=0.15, priority_fee_sol=0.0005):
            self.calls.append((mint, amt)); return "livesig1"
        def submit_sell(self, mint, fraction, price, max_slippage=0.15, priority_fee_sol=0.0005):
            self.calls.append((mint, fraction)); return "sellsig1"

    signer = FakeSigner()
    res = handle_trade_event(db, _trade(w.address, sig="liveevt"), chain=FakeChain(), market=FakeMarket(),
                             notifier=TelegramNotifier(), signer=signer)
    assert res["action"] == "buy"
    assert res["traded"] is True
    assert len(signer.calls) == 1
    lt = db.query(LiveTrade).filter(LiveTrade.source_signature == "liveevt").first()
    assert lt is not None and lt.signature == "livesig1" and lt.status == "submitted"


def test_live_mode_mirrors_leader_sell(db):
    w = _make_tracked_wallet(db, addr="LeaderLiveSell44444444444444444444444444444")
    set_setting(db, "risk", {"enabled": True, "mode": "live", "live_confirmed": True,
                             "fixed_sol_amount": 0.01, "max_position_sol": 0.01,
                             "max_daily_spend_sol": 0.10, "max_daily_loss_sol": 0.03,
                             "min_liquidity_sol": 5, "min_wallet_score": 0, "min_token_score": 0,
                             "max_open_positions_per_token": 1,
                             "live_require_known_token_age": False, "live_min_token_age_seconds": 0, "live_max_token_age_minutes": 0})
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
    reset_engine()

    class FakeSigner:
        def __init__(self): self.buys = []; self.sells = []
        def submit_buy(self, mint, amt, price, max_slippage=0.15, priority_fee_sol=0.0005):
            self.buys.append((mint, amt, price)); return "live-buy-sig"
        def submit_sell(self, mint, fraction, price, max_slippage=0.15, priority_fee_sol=0.0005):
            self.sells.append((mint, fraction, price)); return "live-sell-sig"

    signer = FakeSigner()
    mint = "LiveMirrorSellMint111111111111111111111111"
    buy = handle_trade_event(db, _trade(w.address, mint=mint, side="buy", sig="livebuy1"),
                             chain=FakeChain(), market=FakeMarket(), notifier=TelegramNotifier(), signer=signer)
    assert buy["traded"] is True
    sell = handle_trade_event(db, _trade(w.address, mint=mint, side="sell", sig="livesell1"),
                              chain=FakeChain(), market=FakeMarket(), notifier=TelegramNotifier(), signer=signer)
    assert sell["action"] == "mirror_sell"
    assert sell["traded"] is True
    assert len(signer.sells) == 1
    row = db.query(LiveTrade).filter(LiveTrade.source_signature == "livesell1", LiveTrade.side == "sell").first()
    assert row is not None and row.signature == "live-sell-sig" and row.status == "submitted"


def test_live_mode_blocks_fast_sniper_wallet(db):
    w = _make_tracked_wallet(db, addr="LeaderFastScalper444444444444444444444444")
    w.metrics = {
        "closed_positions": 12,
        "median_hold_seconds": 45,
        "short_hold_ratio": 0.9,
        "copy_sample_size": 8,
        "copyability_score": 82,
        "copy_pnl_10s_sol": 0.1,
    }
    db.commit()
    set_setting(db, "risk", {"enabled": True, "mode": "live", "live_confirmed": True,
                             "fixed_sol_amount": 0.01, "max_position_sol": 0.01,
                             "max_daily_spend_sol": 0.10, "max_daily_loss_sol": 0.03,
                             "min_wallet_score": 0, "min_token_score": 0,
                             "block_sniper_wallets_live": True,
                             "live_min_median_hold_seconds": 300,
                             "live_max_short_hold_ratio": 0.55})
    db.query(PaperTrade).delete(); db.query(LiveTrade).delete(); db.commit()
    reset_engine()

    class FakeSigner:
        def submit_buy(self, *args, **kwargs):
            raise AssertionError("sniper wallet should be blocked before live buy")

    res = handle_trade_event(db, _trade(w.address, sig="fastsniper1"),
                             chain=FakeChain(), market=FakeMarket(),
                             notifier=TelegramNotifier(), signer=FakeSigner())
    assert res["action"] == "skipped"
    assert "Canlı blok" in res["reason"]

"""İşlem kapısı (token_gate) davranışı.

Çekirdek düzeltme: kopya-ticarette cüzdan alpha'dır; token bir GÜVENLİK
filtresidir, ayrı bir kalite eşiği DEĞİL. Taze bonding token'leri (DexScreener'da
likidite yok, holder yoğun) düşük puan alır ama güvenliyse (aktif mint/freeze
yok, satılabilir) işlem AÇILMALIDIR. "score" modunda ise aynı token elenir.
"""
import pytest

from app.adapters.base import ChainProvider, MarketProvider, TokenMarketData
from app.adapters.pumpportal import PumpPortalTrade
from app.models import Wallet, WalletStatus, PaperTrade, Alert, AuditLog
from app.notifications.telegram import TelegramNotifier
from app.services.live_flow import handle_trade_event, reset_engine
from app.services.settings_service import set_setting
from app.trading.risk import RiskConfig, effective_min_token_score


class BondingChain(ChainProvider):
    """Güvenli ama taze bir pump.fun token'i: mint/freeze yetkisi YOK, arz bonding
    curve'de yoğun (holder dağılımı düşük puan üretir)."""
    name = "bonding"

    def get_signatures_for_address(self, address, limit=100):
        return []

    def get_transaction(self, signature):
        return None

    def get_token_supply(self, mint):
        return {"value": {"uiAmount": 1_000_000_000}}

    def get_mint_info(self, mint):
        return {"mintAuthority": None, "freezeAuthority": None}  # renounce => veto YOK

    def get_token_largest_accounts(self, mint):
        return [{"uiAmount": 950_000_000}]  # bonding curve ~tüm arzı tutar


class NoMarket(MarketProvider):
    """DexScreener'da yok (taze bonding) => likidite bilinmiyor (0)."""
    name = "none"

    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=False)


class DangerChain(BondingChain):
    def get_mint_info(self, mint):
        return {"mintAuthority": "ActiveAuth", "freezeAuthority": None}  # => kritik veto


def _wallet(db, addr):
    w = Wallet(address=addr, status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit(); db.refresh(w)
    return w


def _trade(addr, mint, sig):
    return PumpPortalTrade(signature=sig, trader=addr, mint=mint, side="buy",
                           sol_amount=1.0, token_amount=20000, pool="pumpfun",
                           market_cap_sol=100, raw={})


def _safety_risk():
    return {"enabled": True, "mode": "paper", "token_gate": "safety",
            "fixed_sol_amount": 0.05, "max_position_sol": 0.2, "max_daily_spend_sol": 1.0,
            "min_liquidity_sol": 5, "min_wallet_score": 70, "min_token_score": 70}


@pytest.fixture(autouse=True)
def _reset():
    reset_engine(); yield; reset_engine()


def test_effective_min_token_score_by_gate():
    assert effective_min_token_score(RiskConfig(token_gate="safety")) == 0.0
    assert effective_min_token_score(RiskConfig(token_gate="balanced")) == 55.0
    assert effective_min_token_score(RiskConfig(token_gate="score", min_token_score=72)) == 72


def test_safety_gate_trades_low_score_safe_token(db):
    w = _wallet(db, "SafeGateLeader1111111111111111111111111111")
    set_setting(db, "risk", _safety_risk()); reset_engine()
    mint = "FreshBondingMintAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    res = handle_trade_event(db, _trade(w.address, mint, "sg-buy1"),
                             chain=BondingChain(), market=NoMarket(), notifier=TelegramNotifier())
    # Token puanı düşük (bonding) AMA güvenli => safety modunda işlem açılır
    assert res["token_score"] < 70
    assert res["action"] == "buy"
    assert res["token_ok"] is True
    assert res["traded"] is True
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "sg-buy1", PaperTrade.side == "buy").count() == 1
    # Karar Loglar sayfasına yazıldı
    assert db.query(AuditLog).filter(AuditLog.category == "trading").count() >= 1


def test_score_gate_skips_low_score_safe_token(db):
    w = _wallet(db, "ScoreGateLeader222222222222222222222222222")
    r = _safety_risk(); r["token_gate"] = "score"
    set_setting(db, "risk", r); reset_engine()
    mint = "FreshBondingMintBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    res = handle_trade_event(db, _trade(w.address, mint, "sc-buy1"),
                             chain=BondingChain(), market=NoMarket(), notifier=TelegramNotifier())
    # score modunda düşük puan => atlanır, işlem yok, bildirim yok
    assert res["action"] == "skipped"
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "sc-buy1").count() == 0
    assert db.query(Alert).filter(Alert.signature == "sc-buy1").count() == 0


class DecentChain(BondingChain):
    """Olgunlaşmış güvenli token: dağıtık holder'lar (top10 ~%45), 120 holder."""
    def get_token_largest_accounts(self, mint):
        return [{"uiAmount": 45_000_000} for _ in range(10)] + \
               [{"uiAmount": 5_000_000} for _ in range(110)]


class DecentMarket(MarketProvider):
    name = "decent"

    def get_token_market(self, mint):
        import time as _t
        return TokenMarketData(mint=mint, source=self.name, ok=True, liquidity_sol=30.0,
                               market_cap_usd=50000.0, volume_24h_usd=4000.0,
                               pair_created_at=int((_t.time() - 3600) * 1000))


def _balanced_risk():
    r = _safety_risk(); r["token_gate"] = "balanced"; return r


def test_balanced_gate_skips_garbage_but_trades_decent(db):
    """DENGELİ mod (kullanıcı seçimi): çöp (tek-holder bonding ~53) ATLANIR ama
    olgun güvenli token (~80) İŞLEM açar. 'İşlem görelim ama her token'de değil.'"""
    # 1) Çöp token => atlanır
    w1 = _wallet(db, "BalLeaderGarbage11111111111111111111111111")
    set_setting(db, "risk", _balanced_risk()); reset_engine()
    res1 = handle_trade_event(db, _trade(w1.address, "BalGarbageMint1111111111111111111111111111", "bal-g1"),
                              chain=BondingChain(), market=NoMarket(), notifier=TelegramNotifier())
    assert res1["token_score"] < 55
    assert res1["action"] == "skipped"
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "bal-g1").count() == 0

    # 2) Olgun güvenli token => işlem açılır
    w2 = _wallet(db, "BalLeaderDecent222222222222222222222222222")
    set_setting(db, "risk", _balanced_risk()); reset_engine()
    res2 = handle_trade_event(db, _trade(w2.address, "BalDecentMint22222222222222222222222222222", "bal-d1"),
                              chain=DecentChain(), market=DecentMarket(), notifier=TelegramNotifier())
    assert res2["token_score"] >= 55
    assert res2["action"] == "buy"
    assert res2["traded"] is True
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "bal-d1", PaperTrade.side == "buy").count() == 1


def test_safety_gate_still_vetoes_dangerous_token(db):
    """safety modu rug filtresini KORUR: aktif mint yetkisi => işlem yok."""
    w = _wallet(db, "SafeGateLeader3333333333333333333333333333")
    set_setting(db, "risk", _safety_risk()); reset_engine()
    mint = "DangerMintCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    res = handle_trade_event(db, _trade(w.address, mint, "sg-danger1"),
                             chain=DangerChain(), market=NoMarket(), notifier=TelegramNotifier())
    assert res["action"] == "skipped"
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "sg-danger1").count() == 0

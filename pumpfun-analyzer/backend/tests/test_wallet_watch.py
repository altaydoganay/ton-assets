"""Takip edilen cüzdan POLL izleyicisi — UCUZ yol (getSignaturesForAddress +
getTransaction), WS'e bağımlı olmadan işlem tetikler.

Taze bir alım, dengeli kapıyı geçen güvenli bir token için paper işlem açmalı;
tekrar poll'da (dedup) ikinci işlem AÇILMAMALI; eski (stale) imzalar için
getTransaction'a HİÇ gidilmemeli (kredi koruması).
"""
import time

import pytest

from app.adapters.base import ChainProvider, MarketProvider, TokenMarketData
from app.core.analysis.swap_detection import PUMP_FUN_PROGRAM
from app.models import PaperTrade, Wallet, WalletStatus
from app.services.live_flow import reset_engine
from app.services.settings_service import set_setting
from app.services.wallet_watch import poll_tracked_wallets

WALLET = "WatchLeader1111111111111111111111111111111"
MINT = "WatchDecentMint11111111111111111111111111111"


def _raw_buy(wallet, mint, ts, sig):
    """jsonParsed RPC işlemi: cüzdan -1 SOL, +100 token (alım). İmza, imza
    listesindekiyle TUTARLI (üretimde getTransaction(sig).signatures[0]==sig)."""
    return {
        "blockTime": ts, "slot": ts,
        "transaction": {"signatures": [sig], "message": {
            "accountKeys": [{"pubkey": wallet}],
            "instructions": [{"programId": PUMP_FUN_PROGRAM}],
        }},
        "meta": {
            "fee": 5000, "preBalances": [2_000_000_000], "postBalances": [1_000_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmount": 100}}],
        },
    }


def _raw_sell(wallet, mint, ts, sig):
    """jsonParsed RPC işlemi: cüzdan +1 SOL, -100 token (satış)."""
    return {
        "blockTime": ts, "slot": ts,
        "transaction": {"signatures": [sig], "message": {
            "accountKeys": [{"pubkey": wallet}],
            "instructions": [{"programId": PUMP_FUN_PROGRAM}],
        }},
        "meta": {
            "fee": 5000, "preBalances": [1_000_000_000], "postBalances": [2_000_000_000],
            "preTokenBalances": [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmount": 100}}],
            "postTokenBalances": [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmount": 0}}],
        },
    }


class PollChain(ChainProvider):
    """Ucuz yol için imza+işlem; ayrıca token değerlendirmesi (olgun güvenli)."""
    name = "pollchain"

    def __init__(self, sig_times: dict, raw_by_sig: dict):
        self._sig_times = sig_times      # {sig: blockTime}
        self._raw = raw_by_sig           # {sig: raw_tx}

    def get_signatures_for_address(self, address, limit=100):
        return [{"signature": s, "blockTime": bt} for s, bt in self._sig_times.items()]

    def get_transaction(self, signature):
        return self._raw.get(signature)

    def get_token_supply(self, mint):
        return {"value": {"uiAmount": 1_000_000_000}}

    def get_mint_info(self, mint):
        return {"mintAuthority": None, "freezeAuthority": None}

    def get_token_largest_accounts(self, mint):
        return [{"uiAmount": 45_000_000} for _ in range(10)] + \
               [{"uiAmount": 5_000_000} for _ in range(110)]


class DecentMarket(MarketProvider):
    name = "decent"

    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=True, liquidity_sol=30.0,
                               market_cap_usd=50000.0, volume_24h_usd=4000.0,
                               pair_created_at=int((time.time() - 3600) * 1000))


@pytest.fixture(autouse=True)
def _reset():
    reset_engine(); yield; reset_engine()


def _balanced_risk():
    # max_follow_lag_seconds geniş: bu testler İŞLEM TETİKLEMEYİ doğrular, geç-giriş
    # korumasını değil (taze alımlar now-60 olduğundan dar lag eşiği gölgelerdi).
    return {"enabled": True, "mode": "paper", "token_gate": "balanced",
            "fixed_sol_amount": 0.05, "max_position_sol": 0.2, "max_daily_spend_sol": 1.0,
            "min_liquidity_sol": 5, "min_wallet_score": 65, "min_token_score": 70,
            "max_follow_lag_seconds": 900}


def test_poll_triggers_trade_on_fresh_buy_and_dedups(db):
    # Restart-kurtarma (hydrate_from_db) açık pozisyonları PaperTrade'den yeniden
    # kurduğundan, başka testlerden kalan MINT pozisyonu bu alımı (token başına
    # max açık pozisyon) engellemesin diye temiz başla.
    db.query(PaperTrade).delete(); db.commit()
    w = Wallet(address=WALLET, status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", _balanced_risk()); reset_engine()
    now = int(time.time())
    chain = PollChain({"watch-buy-1": now - 60}, {"watch-buy-1": _raw_buy(WALLET, MINT, now - 60, "watch-buy-1")})

    res1 = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=6, fresh_seconds=900)
    assert res1["fresh_buys"] == 1
    assert res1["triggered"] == 1
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "watch-buy-1",
                                       PaperTrade.side == "buy").count() == 1

    res2 = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=6, fresh_seconds=900)
    assert res2["triggered"] == 0  # Alert dedup => çift işlem yok
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "watch-buy-1",
                                       PaperTrade.side == "buy").count() == 1


def test_poll_mirrors_leader_sell(db):
    """Lider SATARSA biz de satarız: açık pozisyonu olan bir token'da satış
    görülünce yansıtılır (mirror_sell)."""
    db.query(PaperTrade).delete()
    db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).delete(); db.commit()
    w = Wallet(address="MirrorLeader1111111111111111111111111111111",
               status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", _balanced_risk()); reset_engine()
    now = int(time.time())
    mint = "MirrorMint11111111111111111111111111111111"
    # 1) ALIM → pozisyon açılır
    buy_chain = PollChain({"mir-buy": now - 120}, {"mir-buy": _raw_buy(w.address, mint, now - 120, "mir-buy")})
    poll_tracked_wallets(db, buy_chain, market=DecentMarket(), per_wallet=6, fresh_seconds=900)
    assert db.query(PaperTrade).filter(PaperTrade.side == "buy", PaperTrade.token_mint == mint).count() == 1
    # 2) SATIŞ → yansıtılır
    sell_chain = PollChain({"mir-sell": now - 30}, {"mir-sell": _raw_sell(w.address, mint, now - 30, "mir-sell")})
    res = poll_tracked_wallets(db, sell_chain, market=DecentMarket(), per_wallet=6, fresh_seconds=900)
    assert res["mirrored_sells"] == 1
    assert db.query(PaperTrade).filter(PaperTrade.side == "sell", PaperTrade.token_mint == mint).count() == 1


def test_poll_ignores_stale_buys_without_fetching(db):
    w = Wallet(address="WatchLeaderStale2222222222222222222222222",
               status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", _balanced_risk()); reset_engine()
    old = int(time.time()) - 7200  # 2 saat önce => taze değil
    # raw_by_sig BOŞ: stale imza için getTransaction çağrılmamalı (yoksa KeyError/None)
    chain = PollChain({"watch-stale-1": old}, {})
    res = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=6, fresh_seconds=900)
    assert res["fresh_buys"] == 0
    assert res["triggered"] == 0


def test_diagnostic_trade_runs_synchronously(db):
    """/trading/test-run mantığı: bir takip cüzdanının son alımını senkron işler
    ve KARARI döner (worker'a gerek yok)."""
    from app.services.wallet_watch import run_diagnostic_trade
    db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).delete(); db.commit()
    w = Wallet(address="DiagLeader11111111111111111111111111111111",
               status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", {**_balanced_risk(), "min_wallet_score": 0}); reset_engine()
    now = int(time.time())
    chain = PollChain({"diag-buy-1": now - 60},
                      {"diag-buy-1": _raw_buy(w.address, "DiagMint111111111111111111111111111111111", now - 60, "diag-buy-1")})
    res = run_diagnostic_trade(db, chain, market=DecentMarket())
    assert res["ok"] is True
    assert res["result"]["action"] == "buy"
    assert res["result"]["traded"] is True


def test_poll_task_writes_panel_heartbeat(db):
    """Poll görevi durumunu Loglar'a (AuditLog category=watch) yazar; 20 dk throttle."""
    from app.models import AuditLog
    from app.workers.tasks import poll_tracked_wallets as task
    # Ağ çağrısı olmasın diye takip cüzdanlarını temizle (poll boş döner)
    db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).delete(); db.commit()
    db.query(AuditLog).filter(AuditLog.category == "watch").delete(); db.commit()
    task(); task()  # ikinci çağrı throttle yüzünden yazmamalı
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.category == "watch").count() == 1

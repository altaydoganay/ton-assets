"""Takip edilen cüzdan POLL izleyicisi — WS'e bağımlı olmadan işlem tetikler.

Enhanced ile çekilen TAZE bir alım, dengeli kapıyı geçen güvenli bir token için
paper işlem açmalı; tekrar poll'da (dedup) ikinci işlem AÇILMAMALIDIR.
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


def _enh_buy(wallet, mint, sig, ts):
    return {
        "signature": sig, "timestamp": ts, "slot": ts, "fee": 5000,
        "source": "PUMP_FUN", "transactionError": None,
        "instructions": [{"programId": PUMP_FUN_PROGRAM, "innerInstructions": []}],
        "accountData": [{"account": wallet, "nativeBalanceChange": -1_000_000_000,
            "tokenBalanceChanges": [{"userAccount": wallet, "mint": mint,
                "rawTokenAmount": {"tokenAmount": "100000000", "decimals": 6}}]}],
    }


class PollChain(ChainProvider):
    """Enhanced destekli + olgun güvenli token verisi sunan sahte sağlayıcı."""
    name = "pollchain"

    def __init__(self, txs):
        self._txs = txs

    def get_address_transactions(self, address, limit=8, before=None, until=None, tx_type=None):
        return self._txs

    def get_signatures_for_address(self, address, limit=100):
        return []

    def get_transaction(self, signature):
        return None

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


def test_poll_triggers_trade_on_fresh_buy_and_dedups(db):
    w = Wallet(address=WALLET, status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", {"enabled": True, "mode": "paper", "token_gate": "balanced",
                             "fixed_sol_amount": 0.05, "max_position_sol": 0.2,
                             "max_daily_spend_sol": 1.0, "min_liquidity_sol": 5,
                             "min_wallet_score": 70, "min_token_score": 70})
    reset_engine()
    now = int(time.time())
    chain = PollChain([_enh_buy(WALLET, MINT, "watch-buy-1", now - 60)])

    res1 = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=8, fresh_seconds=900)
    assert res1["fresh_buys"] == 1
    assert res1["triggered"] == 1
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "watch-buy-1",
                                       PaperTrade.side == "buy").count() == 1

    # İkinci poll: aynı imza => Alert dedup => çift işlem YOK
    res2 = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=8, fresh_seconds=900)
    assert res2["triggered"] == 0
    assert db.query(PaperTrade).filter(PaperTrade.source_signature == "watch-buy-1",
                                       PaperTrade.side == "buy").count() == 1


def test_poll_task_writes_panel_heartbeat(db):
    """Poll görevi durumunu Loglar'a (AuditLog category=watch) yazar; 20 dk throttle."""
    from app.models import AuditLog
    from app.workers.tasks import poll_tracked_wallets as task
    db.query(AuditLog).filter(AuditLog.category == "watch").delete(); db.commit()
    task(); task()  # ikinci çağrı throttle yüzünden yazmamalı
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.category == "watch").count() == 1


def test_poll_ignores_stale_buys(db):
    w = Wallet(address="WatchLeaderStale2222222222222222222222222",
               status=WalletStatus.tracked.value, latest_score=85.0, risk_flags=[])
    db.add(w); db.commit()
    set_setting(db, "risk", {"enabled": True, "mode": "paper", "token_gate": "balanced",
                             "fixed_sol_amount": 0.05, "min_liquidity_sol": 5,
                             "min_wallet_score": 70})
    reset_engine()
    old = int(time.time()) - 7200  # 2 saat önce => taze değil
    chain = PollChain([_enh_buy(w.address, "StaleMint333333333333333333333333333333333", "watch-stale-1", old)])
    res = poll_tracked_wallets(db, chain, market=DecentMarket(), per_wallet=8, fresh_seconds=900)
    assert res["fresh_buys"] == 0
    assert res["triggered"] == 0

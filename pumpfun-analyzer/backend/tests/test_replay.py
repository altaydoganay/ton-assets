"""Geçmiş işlem replay testi — gerçek para/ağ kullanmadan tam hat doğrulaması."""
import time

from app.core.analysis.swap_detection import NormalizedTx, PUMP_FUN_PROGRAM, SYSTEM_PROGRAM, TOKEN_PROGRAM
from app.adapters.base import ChainProvider
from app.services.pipeline import ingest_wallet, analyze_wallet, replay_transactions

WALLET = "ReplayWallet111111111111111111111111111111"
_NOW = int(time.time())


def _ntx(sig, bt, sol, tok, mint, programs, fee=0.0005):
    return NormalizedTx(
        signature=sig, block_time=bt, slot=bt, fee_sol=fee,
        programs=programs, sol_deltas={WALLET: sol},
        token_deltas={(WALLET, mint): tok}, confirmation="finalized",
    )


def _history():
    """12 token üzerinde 24 kapalı pozisyon + araya bir airdrop transferi.

    Zaman ekseni ŞİMDİye sabitlenir: son işlem ~2 gün önce biter (aktiflik
    kriterini geçer); geçmiş ~55 güne yayılır (history_days kriterini geçer)."""
    txs = []
    t = _NOW - 5_000_000  # ~58 gün önce başla
    for i in range(12):
        mint = f"Mint{i}"
        for _ in range(2):
            txs.append(_ntx(f"buy-{i}-{t}", t, -1.0, 100, mint, [PUMP_FUN_PROGRAM, TOKEN_PROGRAM]))
            txs.append(_ntx(f"sell-{i}-{t}", t + 3600, 1.4, -100, mint, [PUMP_FUN_PROGRAM]))
            t += 200_000  # ~2.3 gün; 24 tur => ~55 günlük geçmiş
    # araya saf transfer (swap değil) — sayılmamalı
    txs.append(_ntx("airdrop-1", t, 0.0, 999, "SpamMint", [SYSTEM_PROGRAM, TOKEN_PROGRAM], fee=0.0))
    return txs


def test_replay_full_pipeline(db):
    txs = _history()
    n = replay_transactions(db, WALLET, txs)
    assert n == 48  # 24 buy + 24 sell; airdrop hariç
    res = analyze_wallet(db, WALLET)
    assert res.eligible is True
    assert res.tracked is True
    assert res.total >= 70


class FakeProvider(ChainProvider):
    name = "fake"

    def __init__(self, txmap):
        self.txmap = txmap

    def get_signatures_for_address(self, address, limit=100):
        return [{"signature": s} for s in self.txmap]

    def get_transaction(self, signature):
        return self.txmap.get(signature)

    def get_token_supply(self, mint):
        return None

    def get_mint_info(self, mint):
        return None


def test_ingest_with_rpc_shaped_data(db):
    # RPC jsonParsed benzeri ham işlem -> normalize -> swap tespiti
    raw_buy = {
        "blockTime": 1_700_100_000,
        "slot": 10,
        "transaction": {
            "signatures": ["rawbuy1"],
            "message": {
                "accountKeys": [{"pubkey": WALLET}],
                "instructions": [{"programId": PUMP_FUN_PROGRAM}],
            },
        },
        "meta": {
            "fee": 5000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_000_000_000],  # -1 SOL
            "preTokenBalances": [],
            "postTokenBalances": [
                {"owner": WALLET, "mint": "RawMint", "uiTokenAmount": {"uiAmount": 5000}}
            ],
        },
    }
    provider = FakeProvider({"rawbuy1": raw_buy})
    count = ingest_wallet(db, provider, WALLET)
    assert count == 1
    from app.models import Swap
    s = db.query(Swap).filter(Swap.signature == "rawbuy1").first()
    assert s is not None
    assert s.side == "buy"
    assert s.venue == "pumpfun"

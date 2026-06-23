from datetime import datetime, timezone, timedelta

from app.adapters.base import ChainProvider
from app.models import Swap, Wallet, WalletStatus
from app.services.discovery import (
    record_candidate,
    pending_candidates,
    analyze_discovered_batch,
)


class EmptyProvider(ChainProvider):
    """Yeni işlem getirmeyen sağlayıcı; mevcut swap'lar korunur."""
    name = "empty"
    def get_signatures_for_address(self, address, limit=100): return []
    def get_transaction(self, signature): return None
    def get_token_supply(self, mint): return None
    def get_mint_info(self, mint): return None


def test_record_candidate_and_dedup(db):
    addr = "CandidateWallet11111111111111111111111111111"
    assert record_candidate(db, addr, source="auto") is True
    # ikinci kez => zaten var
    assert record_candidate(db, addr, source="auto") is False
    w = db.query(Wallet).filter(Wallet.address == addr).first()
    assert w is not None and w.status == WalletStatus.discovered.value
    assert w.discovery_source == "auto"


def test_pending_candidates_lists_discovered(db):
    record_candidate(db, "PendingW1111111111111111111111111111111111")
    pend = pending_candidates(db, limit=10)
    assert any(w.address == "PendingW1111111111111111111111111111111111" for w in pend)


def _seed_good_swaps(db, addr):
    """12 token, 24 kapalı kârlı pozisyon, ~55 günlük geçmiş."""
    base = datetime.now(timezone.utc) - timedelta(days=60)
    i = 0
    for tok in range(12):
        mint = f"DiscMint{tok}"
        for _ in range(2):
            t_buy = base + timedelta(days=i * 2.2)
            t_sell = t_buy + timedelta(hours=1)
            db.add(Swap(signature=f"d-buy-{tok}-{i}", wallet_address=addr, token_mint=mint,
                        side="buy", sol_amount=1.0, token_amount=100, price_sol=0.01,
                        fee_sol=0.01, venue="pumpfun", block_time=t_buy, confirmation="finalized"))
            db.add(Swap(signature=f"d-sell-{tok}-{i}", wallet_address=addr, token_mint=mint,
                        side="sell", sol_amount=1.4, token_amount=100, price_sol=0.014,
                        fee_sol=0.01, venue="pumpfun", block_time=t_sell, confirmation="finalized"))
            i += 1
    db.commit()


def test_batch_promotes_quality_wallet_to_tracked(db):
    addr = "GoodDiscovered111111111111111111111111111111"
    record_candidate(db, addr)
    _seed_good_swaps(db, addr)  # mevcut swap'lar; ingest yeni bir şey eklemez
    results = analyze_discovered_batch(db, EmptyProvider(), limit=5, ingest_limit=10)
    mine = [r for r in results if r["address"] == addr]
    assert mine and mine[0]["tracked"] is True
    w = db.query(Wallet).filter(Wallet.address == addr).first()
    assert w.status == WalletStatus.tracked.value
    assert w.latest_score >= 70


def test_batch_marks_empty_wallet_analyzed(db):
    addr = "EmptyDiscovered11111111111111111111111111111"
    record_candidate(db, addr)
    results = analyze_discovered_batch(db, EmptyProvider(), limit=5, ingest_limit=10)
    mine = [r for r in results if r["address"] == addr]
    assert mine and mine[0]["tracked"] is False
    w = db.query(Wallet).filter(Wallet.address == addr).first()
    # artık 'discovered' değil => tekrar analiz kuyruğuna girmez
    assert w.status != WalletStatus.discovered.value
    assert w.last_analyzed is not None

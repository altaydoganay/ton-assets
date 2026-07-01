"""Mevcut cüzdanları depolanmış swap'larla yeniden puanlama (kredi harcamadan).

Kriter/eşik gevşeyince eski 'rejected/below_threshold/analyzed' kararları
güncellenmeli; artık eşiği geçenler TAKİBE alınmalı. blocked KORUNMALI; verisi
olmayan (discovered) cüzdanlar atlanmalı (ingest gerekir, zincire gidilmez)."""
import time

from app.core.analysis.swap_detection import PUMP_FUN_PROGRAM, TOKEN_PROGRAM, NormalizedTx
from app.models import Wallet, WalletStatus
from app.services.analysis_service import get_or_create_wallet
from app.services.pipeline import analyze_wallet, replay_transactions, rescore_wallets_from_storage

_NOW = int(time.time())


def _ntx(wallet, sig, bt, sol, tok, mint, programs, fee=0.0005):
    return NormalizedTx(signature=sig, block_time=bt, slot=bt, fee_sol=fee,
                        programs=programs, sol_deltas={wallet: sol},
                        token_deltas={(wallet, mint): tok}, confirmation="finalized")


def _winning_history(wallet):
    """Takip eşiğini rahat geçen kazançlı geçmiş (12 token, 24 kapalı pozisyon)."""
    txs = []
    t = _NOW - 5_000_000
    for i in range(12):
        mint = f"{wallet[:6]}Mint{i}"
        for _ in range(2):
            txs.append(_ntx(wallet, f"b-{wallet[:5]}-{i}-{t}", t, -1.0, 100, mint, [PUMP_FUN_PROGRAM, TOKEN_PROGRAM]))
            txs.append(_ntx(wallet, f"s-{wallet[:5]}-{i}-{t}", t + 3600, 1.4, -100, mint, [PUMP_FUN_PROGRAM]))
            t += 200_000
    return txs


def test_rescan_promotes_previously_rejected(db):
    addr = "RescanPromote111111111111111111111111111111"
    replay_transactions(db, addr, _winning_history(addr))
    analyze_wallet(db, addr)  # tracked olur
    w = db.query(Wallet).filter(Wallet.address == addr).first()
    assert w.status == WalletStatus.tracked.value
    # Eski katı kurallarda elenmiş gibi davran: durumu geri al
    w.status = WalletStatus.analyzed.value
    db.commit()

    res = rescore_wallets_from_storage(db)
    assert res["to_tracked"] >= 1
    assert addr in res["promoted"]
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.tracked.value


def test_rescan_preserves_blocked(db):
    addr = "RescanBlocked2222222222222222222222222222222"
    replay_transactions(db, addr, _winning_history(addr))
    analyze_wallet(db, addr)
    w = db.query(Wallet).filter(Wallet.address == addr).first()
    w.status = WalletStatus.blocked.value  # kullanıcı/eleme kararı
    db.commit()

    rescore_wallets_from_storage(db)
    # blocked cüzdan yeniden puanlanmaz; durumu korunur (otomatik diriltilmez)
    assert db.query(Wallet).filter(Wallet.address == addr).first().status == WalletStatus.blocked.value


def test_rescan_skips_wallets_without_swaps(db):
    addr = "RescanNoData33333333333333333333333333333333"
    w = get_or_create_wallet(db, addr)  # discovered, swap yok
    w.status = WalletStatus.discovered.value
    db.commit()

    res = rescore_wallets_from_storage(db)
    assert res["skipped_no_data"] >= 1

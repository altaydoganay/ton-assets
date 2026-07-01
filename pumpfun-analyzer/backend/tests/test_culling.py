"""Cüzdan eleme (cull) — aktiflik + kârlılık + örneklem + skor süzgeci."""
from datetime import datetime, timezone, timedelta

from app.models import Swap, Wallet, WalletStatus
from app.services.culling import cull_wallets
from app.services.settings_service import get_setting, set_setting


def _w(db, addr, *, score, pnl, pf, closed, div):
    w = Wallet(address=addr, status=WalletStatus.tracked.value, latest_score=score,
               risk_flags=[], metrics={"realized_pnl_sol": pnl, "profit_factor": pf,
                                        "closed_positions": closed, "token_diversity": div})
    db.add(w); db.commit()
    return w


def _recent_trade(db, addr, days_ago):
    db.add(Swap(signature=f"{addr[:8]}-{days_ago}", wallet_address=addr, token_mint="M",
                side="buy", sol_amount=1.0, token_amount=100, price_sol=0.01, fee_sol=0.0,
                venue="pumpfun", block_time=datetime.now(timezone.utc) - timedelta(days=days_ago),
                confirmation="finalized"))
    db.commit()


def _clean(db):
    db.query(Swap).delete()
    db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).delete()
    db.commit()


def test_cull_keeps_quality_drops_weak(db):
    _clean(db)
    good = _w(db, "CullGood111111111111111111111111111111111", score=80, pnl=2.0, pf=2.5, closed=20, div=8)
    _recent_trade(db, good.address, 1)  # dün işlem yaptı => aktif
    weak = _w(db, "CullWeak222222222222222222222222222222222", score=58, pnl=-1.0, pf=0.6, closed=3, div=1)
    _recent_trade(db, weak.address, 1)

    prev = cull_wallets(db, "strict", dry_run=True)
    assert prev["kept"] == 1 and prev["dropped"] == 1
    # dry_run yazmadı
    assert db.query(Wallet).filter(Wallet.address == weak.address).first().status == WalletStatus.tracked.value

    cull_wallets(db, "strict", dry_run=False)
    assert db.query(Wallet).filter(Wallet.address == good.address).first().status == WalletStatus.tracked.value
    assert db.query(Wallet).filter(Wallet.address == weak.address).first().status == WalletStatus.below_threshold.value


def test_cull_drops_dormant_even_if_profitable(db):
    _clean(db)
    dorm = _w(db, "CullDorm3333333333333333333333333333333333", score=85, pnl=5.0, pf=3.0, closed=30, div=10)
    _recent_trade(db, dorm.address, 20)  # 20 gün önce => uyuyan
    cull_wallets(db, "balanced", dry_run=False)
    assert db.query(Wallet).filter(Wallet.address == dorm.address).first().status == WalletStatus.below_threshold.value


def test_cull_raises_threshold_for_persistence(db):
    _clean(db)
    set_setting(db, "thresholds", {"wallet": 55.0, "token": 70.0})
    g = _w(db, "CullThresh44444444444444444444444444444444", score=80, pnl=2.0, pf=2.0, closed=20, div=8)
    _recent_trade(db, g.address, 1)
    cull_wallets(db, "strict", dry_run=False)
    assert get_setting(db, "thresholds")["wallet"] == 68.0  # bar kalıcı yükseldi


def test_cull_light_only_drops_obvious(db):
    _clean(db)
    # düşük skor + az örneklem ama AKTİF ve KÂRLI => light modda KALIR
    mid = _w(db, "CullMid55555555555555555555555555555555555", score=58, pnl=0.5, pf=1.05, closed=3, div=1)
    _recent_trade(db, mid.address, 1)
    prev = cull_wallets(db, "light", dry_run=True)
    assert prev["kept"] == 1 and prev["dropped"] == 0

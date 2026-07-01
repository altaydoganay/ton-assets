"""Takip üst sınırı (max_tracked): eleme sonrası sayı geri şişmesin.

persist_wallet_score sınır doluyken YENİ cüzdanı takibe almaz; enforce_tracked_cap
sınır aşılırsa en zayıfları indirir; cull sınırı kalıcı olarak ayarlar.
"""
from app.core.scoring.wallet_scoring import WalletScoreResult
from app.models import Wallet, WalletStatus
from app.services.analysis_service import get_or_create_wallet, persist_wallet_score
from app.services.settings_service import get_setting, set_setting
from app.workers.tasks import enforce_tracked_cap


def _tracked_result(total=85.0):
    return WalletScoreResult(
        total=total, performance=total, consistency=total, risk=total, organic=total,
        hold_quality=total, safety=total, recency=total, vetoed=False, eligible=True,
        confidence=0.9, tracked=True)


def _clean(db):
    db.query(Wallet).delete(); db.commit()


def test_persist_blocks_new_track_at_cap(db):
    _clean(db)
    set_setting(db, "thresholds", {"wallet": 55.0, "token": 70.0, "max_tracked": 2})
    # 2 cüzdan takibe alınır (sınır 2)
    for i in range(2):
        w = get_or_create_wallet(db, f"CapFill{i}11111111111111111111111111111111")
        persist_wallet_score(db, w, _tracked_result(), metrics={})
    assert db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).count() == 2
    # 3.'sü puanı yüksek olsa da sınır dolu => takibe ALINMAZ (below_threshold)
    w3 = get_or_create_wallet(db, "CapOver333333333333333333333333333333333333")
    persist_wallet_score(db, w3, _tracked_result(95.0), metrics={})
    assert db.query(Wallet).filter(Wallet.address == w3.address).first().status == WalletStatus.below_threshold.value
    assert db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).count() == 2


def test_persist_unlimited_when_cap_zero(db):
    _clean(db)
    set_setting(db, "thresholds", {"wallet": 55.0, "token": 70.0, "max_tracked": 0})
    for i in range(5):
        w = get_or_create_wallet(db, f"NoCap{i}1111111111111111111111111111111111111")
        persist_wallet_score(db, w, _tracked_result(), metrics={})
    assert db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).count() == 5


def test_enforce_cap_demotes_weakest(db):
    _clean(db)
    set_setting(db, "thresholds", {"wallet": 55.0, "token": 70.0, "max_tracked": 2})
    # Sınırı baypas ederek 4 takip cüzdanı kur (örn. eski kayıtlar / cull öncesi)
    for i, score in enumerate([90, 80, 70, 60]):
        db.add(Wallet(address=f"EnfCap{i}111111111111111111111111111111111111",
                      status=WalletStatus.tracked.value, latest_score=float(score),
                      risk_flags=[], metrics={"realized_pnl_sol": 0.0}))
    db.commit()
    res = enforce_tracked_cap()
    assert res["demoted"] == 2
    tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
    assert len(tracked) == 2
    # En yüksek skorlular kalır (90, 80)
    assert {round(w.latest_score) for w in tracked} == {90, 80}

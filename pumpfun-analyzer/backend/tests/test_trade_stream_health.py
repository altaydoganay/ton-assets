"""Trade akışı sağlığı: PumpPortal funded-anahtar eksikliğinin teşhisi.

Yeni-token akışı canlı ama hiç trade event'i gelmiyorsa (subscribeTokenTrade
funded API anahtarı ister), setup bunu 'trade_stream_ok=False' ile yüzeye çıkarır.
"""
from app.models import AuditLog
from app.services.setup_service import setup_status, _trade_stream_status


def _scan(db, **ctx):
    db.add(AuditLog(level="info", category="ai_scan", message="AI token akışı", context=ctx))
    db.commit()


def test_unknown_when_no_scan(db):
    db.query(AuditLog).delete(); db.commit()
    ts = _trade_stream_status(db)
    assert ts["known"] is False and ts["ok"] is None
    assert setup_status(db)["trade_stream_ok"] is None


def test_dead_trade_stream_detected(db):
    db.query(AuditLog).delete(); db.commit()
    _scan(db, watched=44, trade_age_seconds=-1, trade_stream="dead",
          hint="funded PumpPortal anahtarı gerekli")
    ts = _trade_stream_status(db)
    assert ts["known"] is True and ts["ok"] is False and ts["watched"] == 44
    st = setup_status(db)
    assert st["trade_stream_ok"] is False
    assert "funded" in (st.get("trade_stream_hint") or "")
    chk = next(c for c in st["checks"] if c["key"] == "trade_stream")
    assert chk["ok"] is False and "0.02 SOL" in chk["detail"]


def test_healthy_trade_stream(db):
    db.query(AuditLog).delete(); db.commit()
    _scan(db, watched=30, trade_age_seconds=2)  # trade_stream yok => canlı
    st = setup_status(db)
    assert st["trade_stream_ok"] is True
    chk = next(c for c in st["checks"] if c["key"] == "trade_stream")
    assert chk["ok"] is True


def test_stale_dead_scan_is_ignored(db):
    """Eski (>5 dk) 'dead' ai_scan kaydı yanlış kırmızı göstermemeli (dinleyici değişti)."""
    from datetime import datetime, timezone, timedelta
    db.query(AuditLog).delete(); db.commit()
    old = AuditLog(level="info", category="ai_scan", message="eski",
                   context={"watched": 40, "trade_stream": "dead"})
    db.add(old); db.commit()
    old.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()
    ts = _trade_stream_status(db)
    assert ts["known"] is False and ts["ok"] is None
    assert setup_status(db)["trade_stream_ok"] is None


def test_latest_scan_wins(db):
    db.query(AuditLog).delete(); db.commit()
    _scan(db, watched=10, trade_age_seconds=-1, trade_stream="dead")
    _scan(db, watched=20, trade_age_seconds=3)  # sonraki nabız: iyileşti
    assert _trade_stream_status(db)["ok"] is True

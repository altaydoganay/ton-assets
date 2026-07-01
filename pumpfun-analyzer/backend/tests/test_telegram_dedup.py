from app.notifications.telegram import AlertContent, TelegramNotifier
from app.notifications.dedup import make_dedup_key
from app.models import Alert


def _content(sig="sig1"):
    return AlertContent(
        signature=sig,
        wallet_address="Wallet1111111111111111111111111111111111111",
        wallet_label="Test Cüzdan",
        wallet_score=85,
        token_mint="Mint11111111111111111111111111111111111111",
        token_name="TESTTOKEN",
        token_score=78,
        amount_token=12345,
        sol_value=1.23,
        usd_value=210.5,
        timestamp="2026-06-22T10:00:00Z",
        risk_flags=["Düşük likidite"],
        auto_traded=False,
    )


def test_dedup_key_stable():
    k1 = make_dedup_key("s", "w", "t")
    k2 = make_dedup_key("s", "w", "t")
    assert k1 == k2
    assert make_dedup_key("s", "w", "t") != make_dedup_key("s2", "w", "t")


def test_dedup_key_fits_alerts_column():
    """Regresyon: gerçekçi uzun imza+adresler alerts.dedup_key (varchar 160) için
    TAŞMAMALI. Düz metin ~178 idi ve her alert insert'ini çökertip 0 işleme yol
    açıyordu; özet (hash) sabit 64 karakter."""
    sig = "5" * 88  # Solana base58 imza ~88
    wallet = "A" * 44
    token = "B" * 44
    assert len(make_dedup_key(sig, wallet, token)) <= 160


def test_notify_dedup(db):
    notifier = TelegramNotifier()  # telegram kapalı; gönderim yapılmaz ama kayıt oluşur
    a1 = notifier.notify(db, _content("sigA"))
    assert a1 is not None
    # Aynı imza tekrar => None (dedup)
    a2 = notifier.notify(db, _content("sigA"))
    assert a2 is None
    # Farklı imza => yeni kayıt
    a3 = notifier.notify(db, _content("sigB"))
    assert a3 is not None
    count = db.query(Alert).filter(Alert.signature.in_(["sigA", "sigB"])).count()
    assert count == 2


def test_message_contains_key_fields():
    from app.notifications.telegram import format_message
    msg = format_message(_content())
    assert "85/100" in msg
    assert "TESTTOKEN" in msg
    assert "Otomatik İşlem" in msg

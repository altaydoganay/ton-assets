import logging
import os
import tempfile

from app.security.keystore import Keystore
from app.security.logging_filters import SecretRedactionFilter, redact


SECRET_B58 = "5JZ4q2k9wQ1Q9q8wYxq2k9wQ1Q9q8wYxq2k9wQ1Q9q8wYxq2k9wQ1Q9q8wYxq2k9wQ1Q9q8wYxq2k9wQ1Q9q8wY"


def test_redact_base58_secret():
    out = redact(f"private_key={SECRET_B58}")
    assert SECRET_B58 not in out
    assert "[GIZLI]" in out


def test_redact_api_key():
    out = redact("connecting to wss://pumpportal.fun/api/data?api-key=abc123secretkey")
    assert "abc123secretkey" not in out
    assert "[GIZLI]" in out


def test_redact_keeps_normal_address():
    addr = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    out = redact(f"wallet address {addr}")
    assert addr in out  # public adres maskelenmez


def test_redact_mnemonic():
    seed = "legal winner thank year wave sausage worth useful legal winner thank yellow"
    out = redact(f"seed: {seed}")
    assert "[GIZLI]" in out
    assert "sausage" not in out


def test_log_filter_redacts(caplog):
    logger = logging.getLogger("keytest")
    logger.addFilter(SecretRedactionFilter())
    with caplog.at_level(logging.INFO, logger="keytest"):
        logger.info("loading secret_key=%s now", SECRET_B58)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert SECRET_B58 not in joined


def test_keystore_roundtrip_and_no_plaintext():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        ks = Keystore(path)
        secret = b"\x01" * 64
        ks.store("PubAddr123", secret, passphrase="parola123")
        # Dosyada düz metin secret yok
        with open(path, "rb") as f:
            raw = f.read()
        assert b"\x01" * 64 not in raw
        assert ks.public_address() == "PubAddr123"
        # Doğru parola ile çözülür
        assert ks.unlock("parola123") == secret
    finally:
        os.remove(path)


def test_keystore_wrong_passphrase():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        ks = Keystore(path)
        ks.store("PubAddr", b"\x02" * 64, passphrase="dogru")
        try:
            ks.unlock("yanlis")
            assert False, "yanlış parola hata vermeliydi"
        except ValueError:
            pass
    finally:
        os.remove(path)

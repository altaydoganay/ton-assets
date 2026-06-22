"""Loglara gizli bilgi sızmasını önleyen filtre.

Seed phrase, private key (base58 64-byte veya hex), keystore içeriği ve
parola gibi değerleri log kayıtlarında ve mesaj argümanlarında maskeler.
Cüzdan *adresi* (public key) maskelenmez — yalnızca gizli materyal.
"""
from __future__ import annotations

import logging
import re

# 64-byte base58 secret key (~87-88 karakter) ya da 32-byte (~43-44).
_BASE58_SECRET = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{80,90}\b")
_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{64,128}\b")
# 12/24 kelimelik mnemonic ipucu
_MNEMONIC = re.compile(r"\b(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}\b")
_SENSITIVE_KEYS = ("private_key", "secret_key", "seed", "mnemonic", "passphrase", "keystore", "secret")

REDACTION = "[GIZLI]"


def redact(text: str) -> str:
    if not text:
        return text
    text = _MNEMONIC.sub(REDACTION, text)
    text = _BASE58_SECRET.sub(REDACTION, text)
    text = _HEX_SECRET.sub(REDACTION, text)
    # key=value veya "key": "value" kalıpları
    for key in _SENSITIVE_KEYS:
        text = re.sub(
            rf'("{key}"\s*[:=]\s*")[^"]*(")', rf"\1{REDACTION}\2", text, flags=re.IGNORECASE
        )
        text = re.sub(
            rf"({key}\s*[:=]\s*)(\S+)", rf"\1{REDACTION}", text, flags=re.IGNORECASE
        )
    return text


class SecretRedactionFilter(logging.Filter):
    """Tüm log kayıtlarına uygulanan maskeleme filtresi."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Önce mesajı argümanlarla birlikte render et, sonra maskele.
            # Bu sayede format yer tutucuları (%s) bozulmaz.
            rendered = record.getMessage()
            record.msg = redact(rendered)
            record.args = None
        except Exception:
            # Filtre asla log akışını kırmamalı.
            pass
        return True


def install_redaction(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    flt = SecretRedactionFilter()
    target.addFilter(flt)
    for handler in target.handlers:
        handler.addFilter(flt)

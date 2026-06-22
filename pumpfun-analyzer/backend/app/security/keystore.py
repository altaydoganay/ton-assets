"""Şifreli yerel keystore (trading cüzdanı için güvenli kasa).

- Özel anahtar **asla** düz metin saklanmaz; uygulama parolasıyla türetilen
  anahtar (PBKDF2-HMAC-SHA256) ve Fernet (AES-128-CBC + HMAC) ile şifrelenir.
- Özel anahtar belleğe yalnızca imzalama anında çözülür; diske/log'a/DB'ye
  düz yazılmaz.
- Frontend'e yalnızca public adres döner; secret hiçbir API yanıtında yer almaz.

Not: Gerçek imzalama için `solders`/`solana` kütüphaneleri canlı modda
kullanılır; bu modül anahtar yaşam döngüsü ve şifrelemeden sorumludur.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


@dataclass
class KeystoreEntry:
    public_address: str
    salt: str          # base64
    ciphertext: str    # Fernet token (str)


class Keystore:
    """Tek bir trading cüzdanını şifreli tutan basit dosya tabanlı kasa."""

    def __init__(self, path: str):
        self.path = path

    # --- dosya işlemleri ---
    def _load_raw(self) -> dict | None:
        if not os.path.exists(self.path):
            return None
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self) -> bool:
        return self._load_raw() is not None

    def public_address(self) -> str | None:
        raw = self._load_raw()
        return raw.get("public_address") if raw else None

    # --- şifreleme ---
    def store(self, public_address: str, secret_key_bytes: bytes, passphrase: str) -> KeystoreEntry:
        if not passphrase:
            raise ValueError("Keystore parolası boş olamaz")
        salt = os.urandom(16)
        key = _derive_key(passphrase, salt)
        token = Fernet(key).encrypt(secret_key_bytes)
        entry = {
            "public_address": public_address,
            "salt": base64.b64encode(salt).decode(),
            "ciphertext": token.decode(),
            "version": 1,
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # 0600 izinleriyle yaz
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        return KeystoreEntry(public_address, entry["salt"], entry["ciphertext"])

    def unlock(self, passphrase: str) -> bytes:
        """Özel anahtarı yalnızca imzalama anında çözer. Hata durumunda yükseltir."""
        raw = self._load_raw()
        if not raw:
            raise FileNotFoundError("Keystore bulunamadı")
        salt = base64.b64decode(raw["salt"])
        key = _derive_key(passphrase, salt)
        try:
            return Fernet(key).decrypt(raw["ciphertext"].encode())
        except InvalidToken as exc:
            raise ValueError("Geçersiz parola veya bozuk keystore") from exc

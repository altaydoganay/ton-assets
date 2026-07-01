# Güvenlik Mimarisi

## Özel anahtar yaşam döngüsü
- **Hiçbir** seed phrase / private key frontend'e gönderilmez; API yanıtları
  yalnızca **public adres** döner.
- Anahtar **düz metin** saklanmaz. Şifreleme: PBKDF2-HMAC-SHA256 (480.000
  iterasyon) ile uygulama parolasından anahtar türetilir, **Fernet**
  (AES-128-CBC + HMAC) ile şifrelenir. Dosya `0600` izinleriyle yazılır.
  Kaynak: `backend/app/security/keystore.py`.
- Anahtar belleğe **yalnızca imzalama anında** çözülür (`Keystore.unlock`) ve
  fonksiyon dışına çıkarılmaz.

## Log maskeleme
- `SecretRedactionFilter` tüm log kayıtlarına uygulanır
  (`backend/app/security/logging_filters.py`).
- Maskelenen kalıplar: 80–90 karakter base58 secret, 64–128 hex secret, 12/24
  kelimelik mnemonic, `private_key=`, `secret_key=`, `seed`, `mnemonic`,
  `passphrase`, `keystore` anahtar=değer kalıpları → `[GIZLI]`.
- Cüzdan **adresi** (public key) bilinçli olarak maskelenmez.
- Test güvencesi: `tests/test_key_security.py` — secret'in log'a/dosyaya
  sızmadığını ve adresin korunduğunu doğrular.

## Canlı işlem güvenliği
- Varsayılan mod **paper**. Canlı işlem için: `TRADING_MODE=live`,
  `LIVE_TRADING_CONFIRMED=true` ve geçerli bir keystore gerekir; aksi halde motor
  `LiveTradingNotConfigured` ile reddeder.
- İşlem öncesi risk kontrolleri (`trading/risk.py`): günlük harcama/zarar
  limitleri, maks. pozisyon, slippage, likidite, izleme gecikmesi, engelleme
  listeleri, **acil durdurma**.
- Gönderim öncesi **son güvenlik kontrolü**: token satılabilir mi, puan eşik
  üstünde mi, likidite yeterli mi.
- Arayüz **ayrı ve düşük bakiyeli** trading cüzdanı önerir; ana cüzdan teşvik
  edilmez.

## Hata yönetimi
- RPC failover (birden çok endpoint), blockhash/slippage/yetersiz bakiye/eşzamanlı
  işlem hataları için sağlam yakalama; başarısız canlı işlem `failed` durumuna
  alınır ve gerekçe (gizli bilgi içermeden) saklanır.

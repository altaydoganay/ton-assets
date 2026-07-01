"""Bozuk HELIUS_API_KEY sanitizasyonu (yaygın .env merged-line hatası)."""
from app.config import Settings


def test_merged_line_key_treated_as_empty():
    # Klasik hata: HELIUS_API_KEY=HELIUS_RPC_URL=https://... (iki satır birleşmiş)
    s = Settings(helius_api_key="HELIUS_RPC_URL=https://mainnet.helius-rpc.com/?api-key=")
    assert s.helius_api_key == ""  # bozuk => yok sayılır => Chainstack/RPC yolu kullanılır


def test_url_pasted_as_key_treated_as_empty():
    s = Settings(helius_api_key="https://mainnet.helius-rpc.com/?api-key=abc")
    assert s.helius_api_key == ""


def test_key_with_space_treated_as_empty():
    s = Settings(helius_api_key="abc def")
    assert s.helius_api_key == ""


def test_valid_key_preserved():
    s = Settings(helius_api_key="a1b2c3d4e5f6a7b8c9d0")
    assert s.helius_api_key == "a1b2c3d4e5f6a7b8c9d0"


def test_empty_stays_empty():
    assert Settings(helius_api_key="").helius_api_key == ""
    assert Settings(helius_api_key="   ").helius_api_key == ""

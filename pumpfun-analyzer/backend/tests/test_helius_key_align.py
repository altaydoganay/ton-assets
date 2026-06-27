"""HELIUS_API_KEY değişince eski anahtarın URL'lerde kalmaması (with_api_key).

Senaryo: .env'de HELIUS_RPC_URL/HELIUS_WS_URL içine ESKİ anahtar gömülü; kullanıcı
yalnızca HELIUS_API_KEY'i yeniler. Analiz (Enhanced, yeni anahtar) çalışır ama
poll/WS eski anahtarı kullanırsa kopya işlem DURUR. with_api_key bunu engeller.
"""
from app.adapters.helius import HeliusAdapter, with_api_key


def test_with_api_key_replaces_stale_key():
    url = "https://mainnet.helius-rpc.com/?api-key=ESKI"
    assert with_api_key(url, "YENI") == "https://mainnet.helius-rpc.com/?api-key=YENI"


def test_with_api_key_replaces_in_ws_and_preserves_other_params():
    url = "wss://mainnet.helius-rpc.com/?api-key=ESKI&commitment=confirmed"
    assert with_api_key(url, "YENI") == "wss://mainnet.helius-rpc.com/?api-key=YENI&commitment=confirmed"


def test_with_api_key_appends_when_missing():
    assert with_api_key("https://my-dedicated-node.io/rpc", "YENI") == "https://my-dedicated-node.io/rpc?api-key=YENI"
    assert with_api_key("https://x.io/?foo=1", "YENI") == "https://x.io/?foo=1&api-key=YENI"


def test_with_api_key_noops_on_empty():
    assert with_api_key("", "YENI") == ""
    assert with_api_key("https://x.io/?api-key=ESKI", "") == "https://x.io/?api-key=ESKI"


def test_adapter_standard_rpc_url_uses_current_key():
    # rpc_url ESKİ anahtar gömülü; adapter standart RPC çağrılarını YENİ anahtarla yapmalı
    a = HeliusAdapter(api_key="YENI", rpc_url="https://mainnet.helius-rpc.com/?api-key=ESKI")
    assert "api-key=YENI" in a.endpoints[0]
    assert "ESKI" not in a.endpoints[0]

"""Helius adapteri.

Helius, geliştirilmiş RPC + zenginleştirilmiş işlem (enhanced transactions)
sunar. Standart RPC çağrıları için `SolanaRpcAdapter` davranışını miras alır;
ek olarak enhanced transactions endpoint'ini kullanabilir.
"""
from __future__ import annotations

import re
from typing import Any

from .rpc import SolanaRpcAdapter, Transport


def with_api_key(url: str, key: str) -> str:
    """URL'deki `api-key` parametresini GÜNCEL anahtarla hizalar.

    KRİTİK GÜVENCE: .env'de HELIUS_RPC_URL / HELIUS_WS_URL içine ESKİ anahtar
    gömülü kalmışsa (yalnızca HELIUS_API_KEY değiştirildiğinde sık olur), standart
    RPC (poll = kopya tetikleyici) ve WS dinleyici eski/ölü anahtarı kullanmaya
    devam eder → analiz (Enhanced, yeni anahtar) çalışır ama KOPYA İŞLEM DURUR.
    Bu fonksiyon URL'deki anahtarı her zaman güncel anahtara çeker."""
    if not url or not key:
        return url
    if "api-key=" in url:
        return re.sub(r"api-key=[^&]*", f"api-key={key}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}api-key={key}"


class HeliusAdapter(SolanaRpcAdapter):
    name = "helius"

    def __init__(self, api_key: str, rpc_url: str | None = None, transport: Transport | None = None,
                 min_interval: float = 0.0, rate_limit_retries: int = 6):
        self.api_key = api_key
        # rpc_url verilmişse içindeki (muhtemelen eski) anahtarı güncel anahtara hizala.
        url = with_api_key(rpc_url, api_key) if rpc_url else f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        super().__init__(endpoints=[url], transport=transport,
                         min_interval=min_interval, rate_limit_retries=rate_limit_retries)
        self._enhanced_base = "https://api.helius.xyz/v0"

    def get_enhanced_transactions(self, signatures: list[str]) -> list[dict[str, Any]]:
        """Enhanced transactions (parse edilmiş swap/transfer bilgisi)."""
        import httpx

        url = f"{self._enhanced_base}/transactions?api-key={self.api_key}"
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, json={"transactions": signatures})
            resp.raise_for_status()
            return resp.json()

    def get_address_transactions(
        self,
        address: str,
        limit: int = 100,
        before: str | None = None,
        until: str | None = None,
        tx_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Bir adresin parse edilmiş işlem GEÇMİŞİ — TEK istekte 100 işleme kadar.

        KREDİ KRİTİK: 100 ayrı `getTransaction` çağrısı yerine bu endpoint tek HTTP
        isteğiyle 100 parse edilmiş işlem döner (≈100× daha az kredi). Cüzdan
        analizinde derin ve eksiksiz geçmiş bu sayede ucuza elde edilir.

        En yeniden eskiye sıralı döner; sayfalama için `before=<son imza>` ver.
        """
        import httpx

        url = f"{self._enhanced_base}/addresses/{address}/transactions"
        params: dict[str, Any] = {
            "api-key": self.api_key,
            "limit": max(1, min(int(limit), 100)),
        }
        if before:
            params["before"] = before
        if until:
            params["until"] = until
        if tx_type:
            params["type"] = tx_type
        with httpx.Client(timeout=25) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

"""Telegram bildirim servisi.

Kayıtlı (puan>=70) bir cüzdan, kayıtlı (puan>=70) bir tokeni satın aldığında
bildirim gönderir. Aynı işlem için dedup uygulanır (alerts tablosu + dedup_key).

Ağ çağrısı `httpx` ile yapılır; test ortamında `send` enjekte edilebilir bir
transport ile mock'lanabilir. Telegram kapalıysa veya token yoksa mesaj
oluşturulur ama gönderilmez (kayıt yine de işaretlenir).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import settings
from sqlalchemy.orm import Session

from ..models import Alert
from .dedup import make_dedup_key

logger = logging.getLogger(__name__)


@dataclass
class AlertContent:
    signature: str
    wallet_address: str
    wallet_label: str | None
    wallet_score: float
    token_mint: str
    token_name: str | None
    token_score: float
    amount_token: float
    sol_value: float
    usd_value: float | None
    timestamp: str
    risk_flags: list[str]
    auto_traded: bool


def short_addr(addr: str) -> str:
    return f"{addr[:4]}…{addr[-4:]}" if len(addr) > 10 else addr


def format_message(c: AlertContent) -> str:
    name = c.wallet_label or short_addr(c.wallet_address)
    tname = c.token_name or short_addr(c.token_mint)
    usd = f"${c.usd_value:,.2f}" if c.usd_value is not None else "—"
    risks = ", ".join(c.risk_flags) if c.risk_flags else "Belirgin uyarı yok"
    tx_link = f"https://solscan.io/tx/{c.signature}"
    token_link = f"/tokens/{c.token_mint}"
    auto = "Evet" if c.auto_traded else "Hayır"
    return (
        f"🟢 *Takipteki cüzdan alım yaptı*\n\n"
        f"👛 Cüzdan: `{name}` ({short_addr(c.wallet_address)})\n"
        f"⭐ Cüzdan Puanı: *{c.wallet_score:.0f}/100*\n\n"
        f"🪙 Token: *{tname}*\n"
        f"`{c.token_mint}`\n"
        f"⭐ Token Puanı: *{c.token_score:.0f}/100*\n\n"
        f"💰 Miktar: {c.amount_token:,.0f}\n"
        f"◎ SOL Değeri: {c.sol_value:.4f}\n"
        f"💵 USD Değeri: {usd}\n"
        f"🕒 Zaman: {c.timestamp}\n\n"
        f"⚠️ Riskler: {risks}\n"
        f"🤖 Otomatik İşlem: {auto}\n\n"
        f"🔗 [İşlem]({tx_link}) · [Token Analizi]({token_link})"
    )


class TelegramNotifier:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = settings.telegram_enabled

    def _post(self, text: str) -> bool:
        if not (self.enabled and self.bot_token and self.chat_id):
            logger.info("Telegram kapalı veya yapılandırılmamış; mesaj gönderilmedi")
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False}
        client = self._client or httpx.Client(timeout=10)
        try:
            resp = client.post(url, json=payload)
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram gönderimi başarısız: %s", exc)
            return False
        finally:
            if self._client is None:
                client.close()

    def notify(self, db: Session, content: AlertContent) -> Alert | None:
        """Dedup uygula ve gönder. Daha önce gönderildiyse None döner."""
        key = make_dedup_key(content.signature, content.wallet_address, content.token_mint)
        existing = db.query(Alert).filter(Alert.dedup_key == key).first()
        if existing:
            logger.info("Bildirim zaten mevcut (dedup): %s", key)
            return None

        text = format_message(content)
        sent = self._post(text)
        alert = Alert(
            dedup_key=key,
            signature=content.signature,
            wallet_address=content.wallet_address,
            token_mint=content.token_mint,
            wallet_score=content.wallet_score,
            token_score=content.token_score,
            payload={"message": text, "risk_flags": content.risk_flags},
            sent=sent,
            auto_traded=content.auto_traded,
        )
        from datetime import datetime, timezone
        if sent:
            alert.sent_at = datetime.now(timezone.utc)
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert

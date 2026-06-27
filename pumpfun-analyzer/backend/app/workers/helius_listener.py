"""Helius WebSocket dinleyicisi — keşif + takip (PumpPortal ücretini ödemeden).

Helius WS (`logsSubscribe`) senin planına dahildir; SOL ücreti YOKTUR. İki iş:

  A) TAKİP: her takip edilen cüzdan için `logsSubscribe mentions=[cüzdan]`.
     Bildirim gelince işlem getTransaction ile çekilir, swap tespit edilir ve
     bildirim + (ayar açıksa) kopya işlem tetiklenir.

  B) KEŞİF: pump.fun programına `logsSubscribe mentions=[PUMP_FUN_PROGRAM]`.
     Gelen işlemlerden ALICILAR çıkarılır; birden fazla farklı token alanlar
     `discovered` olarak kaydedilir. Ücretsiz Helius kredisini korumak için keşif
     getTransaction çağrıları DAKİKADA `discovery_max_lookups_per_min` ile
     SINIRLANIR (fazlası düşürülür). Takip işlemleri her zaman işlenir.

Gerçek al-sat hâlâ PumpPortal Lightning ile yapılır (signer enjekte edilir).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict

from ..config import settings
from ..database import SessionLocal
from ..adapters.pumpfun import normalize_rpc_transaction
from ..adapters.pumpportal import PumpPortalTrade, PumpPortalTrader
from ..adapters.registry import build_chain_provider
from ..core.analysis.swap_detection import (
    PUMP_FUN_PROGRAM,
    PUMP_SWAP_PROGRAM,
    detect_swap,
    extract_buyers,
)
from ..models import Wallet, WalletStatus
from ..notifications.telegram import TelegramNotifier
from ..services.discovery import record_candidate
from ..services.live_flow import handle_trade_event

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 30


def _ws_url() -> str:
    if settings.helius_ws_url:
        # .env'de eski anahtar gömülü kalmışsa güncel HELIUS_API_KEY'e hizala
        from ..adapters.helius import with_api_key
        return with_api_key(settings.helius_ws_url, settings.helius_api_key) if settings.helius_api_key else settings.helius_ws_url
    if settings.helius_api_key:
        return f"wss://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
    return settings.solana_ws_url


def _tracked_addresses() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(Wallet.address).filter(Wallet.status == WalletStatus.tracked.value).all()
        return [r[0] for r in rows]
    finally:
        db.close()


def _discovery_on() -> bool:
    """Keşif akışı (pump.fun firehose) açık mı — panelden (DB) kontrol edilebilir.
    Kapalıyken WS firehose'a abone OLMAYIZ; bu, Helius streaming kredisinin (MB
    başına) ana kalemini durdurur. 14k+ aday backlog'u varken bunu kapatmak
    krediyi büyük ölçüde düşürür; analiz mevcut backlog üzerinde devam eder."""
    db = SessionLocal()
    try:
        from ..services.settings_service import get_runtime_flag
        return get_runtime_flag(db, "discovery_enabled", settings.discovery_enabled)
    except Exception:  # noqa: BLE001
        return settings.discovery_enabled
    finally:
        db.close()


def _listener_on() -> bool:
    """Canlı WS dinleyicisi (TÜM abonelikler) açık mı — panelden kontrol edilir.
    Kapalıyken hem keşif firehose'u hem de cüzdan-başına abonelikler İPTAL edilir;
    WS boş kalır (≈0 streaming kredisi). Kopya işlem POLL ile devam eder
    (poll_tracked_wallets her ~60 sn). Gerçek-zaman görünürlüğü yerine kredi
    tasarrufu isteyen kullanıcı için ana kapatma anahtarı."""
    db = SessionLocal()
    try:
        from ..services.settings_service import get_runtime_flag
        return get_runtime_flag(db, "listener_enabled", settings.live_listener_enabled)
    except Exception:  # noqa: BLE001
        return settings.live_listener_enabled
    finally:
        db.close()


class _RateLimiter:
    """Dakikalık kayan pencere sayacı."""
    def __init__(self, per_min: int):
        self.per_min = per_min
        self._stamps: list[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t < 60]
        if len(self._stamps) >= self.per_min:
            return False
        self._stamps.append(now)
        return True


class HeliusListener:
    def __init__(self, signer: PumpPortalTrader | None = None):
        self.signer = signer
        self.notifier = TelegramNotifier()
        # hızlı (throttle kapalı) sağlayıcı — canlı/keşif getTransaction için
        self.chain = build_chain_provider(throttle=False)
        self.stat_lookups = 0      # keşif için incelenen işlem sayısı
        self.stat_candidates = 0   # eklenen yeni aday sayısı
        self.sub_meta: dict[int, tuple[str, str | None]] = {}  # sub_id -> (kind, wallet)
        self.pending: dict[int, tuple[str, str | None]] = {}   # req_id -> (kind, wallet)
        self.subscribed_accounts: set[str] = set()
        self.discovery_sub_active = False
        self.buyer_hits: dict[str, set[str]] = {}
        self.known_candidates: set[str] = set()
        self.limiter = _RateLimiter(settings.discovery_max_lookups_per_min)
        self._req_id = 1000

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _subscribe_logs(self, ws, mentions: str, kind: str, wallet: str | None):
        rid = self._next_id()
        self.pending[rid] = (kind, wallet)
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": "logsSubscribe",
            "params": [{"mentions": [mentions]}, {"commitment": "confirmed"}],
        }))

    def _heartbeat(self):
        db = SessionLocal()
        try:
            from ..services.settings_service import set_heartbeat
            set_heartbeat(db)
        except Exception:  # noqa: BLE001
            pass
        finally:
            db.close()

    async def _unsubscribe_all(self, ws):
        """Tüm abonelikleri (keşif + cüzdan) iptal et — WS boş kalır, ≈0 kredi."""
        for sid in list(self.sub_meta.keys()):
            try:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": self._next_id(),
                                          "method": "logsUnsubscribe", "params": [sid]}))
            except Exception:  # noqa: BLE001
                pass
        self.sub_meta.clear()
        self.subscribed_accounts.clear()
        self.discovery_sub_active = False

    async def _refresh(self, ws):
        listener_was_on = True
        while True:
            try:
                await asyncio.to_thread(self._heartbeat)
                # ASCII etiketli durum logu (Windows findstr ile aranabilir)
                logger.info("[DISCOVERY] lookups=%d candidates=%d tracked_subs=%d",
                            self.stat_lookups, self.stat_candidates, len(self.subscribed_accounts))
                # ANA KAPATMA: dinleyici kapalıysa TÜM abonelikleri durdur (kredi
                # tasarrufu) ve abone OLMA — kopya işlem POLL ile sürer.
                listener_on = await asyncio.to_thread(_listener_on)
                if not listener_on:
                    if listener_was_on:
                        await self._unsubscribe_all(ws)
                        logger.info("[LISTENER] Canlı dinleyici KAPALI — tüm abonelikler durduruldu "
                                    "(kredi koruması; kopya işlem POLL ile sürer)")
                    listener_was_on = False
                    await asyncio.sleep(REFRESH_SECONDS)
                    continue
                listener_was_on = True
                want_discovery = await asyncio.to_thread(_discovery_on)
                if want_discovery and not self.discovery_sub_active:
                    await self._subscribe_logs(ws, PUMP_FUN_PROGRAM, "discovery", None)
                    self.discovery_sub_active = True
                    # Mezun olmuş (PumpSwap) token alıcıları da kaliteli sinyaldir
                    await self._subscribe_logs(ws, PUMP_SWAP_PROGRAM, "discovery", None)
                    logger.info("[LISTENER] keşif akışı AÇIK (pump.fun firehose)")
                elif not want_discovery and self.discovery_sub_active:
                    # Firehose'u DURDUR: discovery aboneliklerini iptal et (kredi koruması)
                    for sid in [s for s, (k, _w) in self.sub_meta.items() if k == "discovery"]:
                        try:
                            await ws.send(json.dumps({"jsonrpc": "2.0", "id": self._next_id(),
                                                      "method": "logsUnsubscribe", "params": [sid]}))
                        except Exception:  # noqa: BLE001
                            pass
                        self.sub_meta.pop(sid, None)
                    self.discovery_sub_active = False
                    logger.info("[LISTENER] keşif akışı KAPALI (firehose durduruldu — kredi koruması)")
                current = set(_tracked_addresses())
                for addr in current - self.subscribed_accounts:
                    await self._subscribe_logs(ws, addr, "tracked", addr)
                    self.subscribed_accounts.add(addr)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Abonelik tazeleme hatası: %s", exc)
            await asyncio.sleep(REFRESH_SECONDS)

    async def process(self, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        # abonelik onayı: id -> sub_id eşle
        if "result" in msg and "id" in msg and isinstance(msg.get("result"), int):
            meta = self.pending.pop(msg["id"], None)
            if meta:
                self.sub_meta[msg["result"]] = meta
            return
        if msg.get("method") != "logsNotification":
            return
        params = msg.get("params") or {}
        sub_id = params.get("subscription")
        meta = self.sub_meta.get(sub_id)
        if not meta:
            return
        kind, wallet = meta
        value = (params.get("result") or {}).get("value") or {}
        if value.get("err") is not None:
            return  # başarısız işlemi atla
        sig = value.get("signature")
        if not sig:
            return
        if kind == "tracked":
            await asyncio.to_thread(self._handle_tracked, sig, wallet)
        elif kind == "discovery":
            if self.limiter.allow():
                await asyncio.to_thread(self._handle_discovery, sig)
            # limit aşıldıysa bu keşif olayını düşür (kredi koruması)

    def _fetch_ntx(self, sig: str):
        raw = self.chain.get_transaction(sig)
        return normalize_rpc_transaction(raw) if raw else None

    def _handle_tracked(self, sig: str, wallet: str):
        db = SessionLocal()
        try:
            ntx = self._fetch_ntx(sig)
            if ntx is None:
                return
            swap = detect_swap(ntx, wallet)
            if swap is None:
                return
            trade = PumpPortalTrade(
                signature=swap.signature, trader=swap.wallet_address, mint=swap.token_mint,
                side=swap.side, sol_amount=swap.sol_amount, token_amount=swap.token_amount,
                pool=swap.venue, market_cap_sol=None, raw={},
            )
            handle_trade_event(db, trade, chain=self.chain, notifier=self.notifier, signer=self.signer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Takip olayı işlenemedi: %s", exc)
        finally:
            db.close()

    def _handle_discovery(self, sig: str):
        self.stat_lookups += 1
        try:
            ntx = self._fetch_ntx(sig)
            if ntx is None:
                return
            for wallet, mint in extract_buyers(ntx):
                self._record_buyer(wallet, mint)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DISCOVERY] olay atlandı: %s", exc)

    def _record_buyer(self, trader: str, mint: str):
        if trader in self.known_candidates:
            return
        hits = self.buyer_hits.setdefault(trader, set())
        hits.add(mint)
        if len(hits) >= settings.discovery_min_token_hits:
            self.known_candidates.add(trader)
            self.buyer_hits.pop(trader, None)
            db = SessionLocal()
            try:
                if record_candidate(db, trader, source="auto-helius"):
                    self.stat_candidates += 1
                    logger.info("[DISCOVERY] new candidate %s", trader)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[DISCOVERY] aday kaydedilemedi: %s", exc)
            finally:
                db.close()
        if len(self.buyer_hits) > 20000:
            self.buyer_hits.clear()
        if len(self.known_candidates) > 50000:
            self.known_candidates.clear()

    async def run(self, stop_event: asyncio.Event | None = None):
        import websockets

        url = _ws_url()
        if not settings.helius_api_key and "api-key" not in url:
            logger.warning("Helius API anahtarı yok; dinleyici sınırlı çalışır.")
        backoff = 1.0
        while stop_event is None or not stop_event.is_set():
            self.sub_meta.clear()
            self.pending.clear()
            self.subscribed_accounts.clear()
            self.discovery_sub_active = False
            try:
                async with websockets.connect(url, ping_interval=20, max_size=8_000_000) as ws:
                    logger.info("[LISTENER] Helius WS connected (discovery=%s)", settings.discovery_enabled)
                    backoff = 1.0
                    refresher = asyncio.create_task(self._refresh(ws))
                    try:
                        async for raw in ws:
                            if stop_event is not None and stop_event.is_set():
                                break
                            await self.process(raw)
                    finally:
                        refresher.cancel()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Helius WS koptu (%.0fs sonra tekrar): %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


async def run_helius_listener(stop_event: asyncio.Event | None = None) -> None:
    signer = PumpPortalTrader() if settings.pumpportal_api_key else None
    await HeliusListener(signer=signer).run(stop_event)

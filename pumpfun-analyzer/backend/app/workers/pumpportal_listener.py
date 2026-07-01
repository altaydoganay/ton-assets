"""PumpPortal canlı veri dinleyicisi + otomatik cüzdan keşfi.

Tek bir WebSocket bağlantısı üzerinden iki işi birlikte yapar:

  A) TAKİP: takip edilen (puan ≥ eşik) cüzdanların gerçek al-sat işlemlerine
     `subscribeAccountTrade` ile abone olur; olay gelince bildirim + (ayar
     açıksa) kopya işlem tetiklenir.

  B) KEŞİF (otomatik): `subscribeNewToken` ile yeni Pump.fun tokenlerini yakalar,
     bunların işlemlerine abone olur ve bu tokenleri ALAN cüzdanları toplar.
     Birden fazla farklı token üzerinde alım yapan cüzdanlar `discovered` olarak
     veritabanına yazılır; arka plan (Celery beat) bunları analiz edip puanlar.

Bağlantı koparsa üssel geri çekilmeyle yeniden bağlanır. Tüm bloklayıcı DB/HTTP
işleri ayrı thread'e taşınır (event loop kilitlenmez).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict

from ..config import settings
from ..database import SessionLocal
from ..adapters.pumpportal import PumpPortalTrader, parse_trade_event
from ..models import Wallet, WalletStatus, AuditLog
from ..notifications.telegram import TelegramNotifier
from ..services.discovery import record_candidate
from ..services.live_flow import handle_trade_event

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 30


def _tracked_addresses() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(Wallet.address).filter(Wallet.status == WalletStatus.tracked.value).all()
        return [r[0] for r in rows]
    finally:
        db.close()


def _strategy_mode() -> str:
    db = SessionLocal()
    try:
        from ..services.settings_service import get_setting
        risk = get_setting(db, "risk")
        return str(risk.get("strategy_mode", "copy") or "copy")
    except Exception:  # noqa: BLE001
        return "copy"
    finally:
        db.close()


def _ai_policy() -> dict:
    """AI listener için etkin fırsat penceresi.

    Bu sadece abonelik/akış gürültüsünü azaltır. Nihai karar yine live_flow
    içindeki AI karar motorundadır.
    """
    db = SessionLocal()
    try:
        from ..services.settings_service import get_setting, resolve_ai_policy
        return resolve_ai_policy(get_setting(db, "risk"))
    except Exception:  # noqa: BLE001
        return {"ai_fresh_universe_enabled": True, "ai_max_token_age_minutes": 90}
    finally:
        db.close()


def _is_new_token(msg: dict) -> bool:
    if msg.get("txType") in ("buy", "sell"):
        return False
    if not msg.get("mint"):
        return False
    # Yeni token olayları genelde create/isim/uri taşır.
    return msg.get("txType") == "create" or "uri" in msg or "name" in msg


class PumpPortalListener:
    def __init__(self, signer: PumpPortalTrader | None = None):
        self.signer = signer
        self.notifier = TelegramNotifier()
        self.tracked: set[str] = set()
        self.subscribed_accounts: set[str] = set()
        self.watched_tokens: "OrderedDict[str, float]" = OrderedDict()  # mint -> first-seen unix time
        self.buyer_hits: dict[str, set[str]] = {}
        self.known_candidates: set[str] = set()
        # BUILD 70: WS okuma döngüsü asla token analizi/trade kararını beklemesin.
        # Ağ/DB/market çağrıları kuyruk işçilerine atılır; böylece yeni token
        # akışı kaçırılmaz.
        self.event_queue: asyncio.Queue[PumpPortalTrade] | None = None
        self.last_ai_signal_by_mint: dict[str, float] = {}
        self.stat_queued = 0
        self.stat_processed = 0
        self.stat_dropped = 0
        self.stat_drop_stale = 0
        self.last_raw_at = 0.0
        self.last_new_token_at = 0.0
        self.last_trade_at = 0.0
        self.last_reconnect_reason = ""
        self.last_audit_at = 0.0
        self.last_warning_audit_at = 0.0

    # --- abonelik bakımı ---
    async def _refresh_accounts(self, ws):
        while True:
            try:
                # Mod izolasyonu: AI Trade seçiliyken cüzdan/account aboneliği yok.
                # Böylece copy buy/sell event'leri AI modunda arka planda çalışmaz.
                if _strategy_mode() != "copy":
                    if self.subscribed_accounts:
                        try:
                            await ws.send(json.dumps({"method": "unsubscribeAccountTrade", "keys": list(self.subscribed_accounts)}))
                        except Exception:  # noqa: BLE001
                            pass
                        logger.info("AI modu aktif: %d copy cüzdan aboneliği kapatıldı", len(self.subscribed_accounts))
                    self.tracked.clear()
                    self.subscribed_accounts.clear()
                    await asyncio.sleep(REFRESH_SECONDS)
                    continue

                current = set(_tracked_addresses())
                self.tracked = current
                new = current - self.subscribed_accounts
                if new:
                    await ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": list(new)}))
                    self.subscribed_accounts |= new
                    logger.info("Takip aboneliği: +%d (toplam %d)", len(new), len(self.subscribed_accounts))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Abonelik tazeleme hatası: %s", exc)
            await asyncio.sleep(REFRESH_SECONDS)

    async def _unwatch_token(self, ws, mint: str):
        self.watched_tokens.pop(mint, None)
        try:
            await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": [mint]}))
        except Exception:  # noqa: BLE001
            pass

    async def _watch_token(self, ws, mint: str, created_ts: float | None = None):
        created_ts = float(created_ts or time.time())
        if mint in self.watched_tokens:
            self.watched_tokens.move_to_end(mint)
            # İlk görülen zamanı koru; yeni mesaj geldikçe token yaşını sıfırlama.
            return
        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
        self.watched_tokens[mint] = created_ts
        await self._prune_watched_tokens(ws)

    async def _prune_watched_tokens(self, ws):
        """İzlenen token havuzunu yaş ve kapasiteye göre temizle.

        BUILD 70: Kapasiteye gelmeden önce AI yaş penceresi dolan tokenları atar.
        Böylece 1500 token kapasite uzun süre dolu kalmaz ve en yeni tokenlar
        abonelik dışı kalmaz.
        """
        now = time.time()
        strategy = _strategy_mode()
        max_tokens = int(settings.discovery_max_watched_tokens)
        max_age_seconds = 0.0
        if strategy == "ai":
            policy = _ai_policy()
            max_age_seconds = float(policy.get("ai_max_token_age_minutes", 90) or 0) * 60.0
        if max_age_seconds > 0:
            for mint, first_seen in list(self.watched_tokens.items()):
                if now - float(first_seen) > max_age_seconds + 30.0:
                    await self._unwatch_token(ws, mint)
        # kapasite aşımında en eskiyi bırak
        while len(self.watched_tokens) > max_tokens:
            old, _ = self.watched_tokens.popitem(last=False)
            try:
                await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": [old]}))
            except Exception:  # noqa: BLE001
                pass

    async def _drop_stale_ai_token_if_needed(self, ws, mint: str) -> bool:
        """AI modunda eski tokenları akıştan çıkar.

        Daha önce yeni token diye izlemeye aldığımız bir mint saatlerce listede
        kalırsa, sonradan gelen küçük hareketler AI paper alımı üretebiliyordu.
        AI Trade'in ana evreni taze launch tokenları olduğu için süre dolunca
        aboneliği kapatır ve trade event'ini işlemez.
        """
        first_seen = self.watched_tokens.get(mint)
        if not first_seen:
            return False
        policy = _ai_policy()
        if not bool(policy.get("ai_fresh_universe_enabled", True)):
            return False
        max_age_min = float(policy.get("ai_max_token_age_minutes", 90) or 0)
        if max_age_min <= 0:
            return False
        age = time.time() - float(first_seen)
        # Küçük tolerans: event gecikmesi ve saat farkları yüzünden sınırdaki
        # tokenı yanlışlıkla atmayalım.
        if age > max_age_min * 60.0 + 30.0:
            await self._unwatch_token(ws, mint)
            logger.info("AI token izleme kapatıldı: %s eski (%.1f dk > %.1f dk)", mint, age / 60.0, max_age_min)
            return True
        return False

    def _ai_signal_cooldown_ok(self, mint: str) -> bool:
        cooldown = float(settings.ai_signal_token_cooldown_seconds or 0)
        if cooldown <= 0:
            return True
        now = time.monotonic()
        last = self.last_ai_signal_by_mint.get(mint, 0.0)
        if now - last < cooldown:
            return False
        self.last_ai_signal_by_mint[mint] = now
        # bellek koruması
        if len(self.last_ai_signal_by_mint) > 20000:
            cutoff = now - max(60.0, cooldown * 20)
            self.last_ai_signal_by_mint = {k: v for k, v in self.last_ai_signal_by_mint.items() if v >= cutoff}
        return True

    async def _enqueue_trade(self, trade: PumpPortalTrade) -> None:
        """Trade kararını arka plan kuyruğuna at.

        Önceden process() doğrudan await asyncio.to_thread(handle_trade_event)
        yapıyordu. Token analizi 0.5-3 sn sürerse WebSocket okuma döngüsü bloke
        oluyor ve yeni token event'leri kaçıyordu. BUILD 70'te process() sadece
        kuyruğa koyar; worker'lar paralel işler.
        """
        if self.event_queue is None:
            await asyncio.to_thread(self._handle_tracked, trade)
            return
        # Çok gecikmiş AI sinyalini işlemek tepeden alma riskidir; kuyruk şişerse
        # eski sinyali bırakmak yeni token yakalamaktan daha doğrudur.
        received = None
        try:
            received = float((trade.raw or {}).get("_received_at") or 0.0)
        except Exception:  # noqa: BLE001
            received = None
        if received and (time.time() - received) > int(settings.ai_signal_drop_if_older_seconds):
            self.stat_drop_stale += 1
            return
        try:
            self.event_queue.put_nowait(trade)
            self.stat_queued += 1
        except asyncio.QueueFull:
            self.stat_dropped += 1
            try:
                _old = self.event_queue.get_nowait()
                self.event_queue.task_done()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.event_queue.put_nowait(trade)
                self.stat_queued += 1
            except Exception:  # noqa: BLE001
                self.stat_dropped += 1

    async def _event_worker(self, idx: int):
        assert self.event_queue is not None
        while True:
            trade = await self.event_queue.get()
            try:
                # Kuyrukta çok bekleyen sinyal yeni token fırsatı değil, gecikmiş
                # giriş riskidir. Copy sell/buy için de geç kalmış olayları işlememek
                # yerine mevcut handler dedup/risk kapısından geçer; burada yalnızca
                # AI buy için sert yaş uygulanır.
                received = float((trade.raw or {}).get("_received_at") or 0.0)
                if trade.trader == "AI_TRADE" or (trade.raw or {}).get("_strategy") == "ai":
                    if received and (time.time() - received) > int(settings.ai_signal_drop_if_older_seconds):
                        self.stat_drop_stale += 1
                        continue
                await asyncio.to_thread(self._handle_tracked, trade)
                self.stat_processed += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Trade worker-%d olayı işleyemedi: %s", idx, exc)
            finally:
                self.event_queue.task_done()

    # --- mesaj işleme ---
    async def process(self, ws, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        self.last_raw_at = time.time()
        if msg.get("errors") or msg.get("error"):
            logger.warning("PumpPortal WS hata mesajı: %s", msg)

        strategy = _strategy_mode()
        if (settings.discovery_enabled or strategy == "ai") and _is_new_token(msg):
            self.last_new_token_at = time.time()
            await self._watch_token(ws, msg["mint"], created_ts=time.time())
            return

        trade = parse_trade_event(msg)
        if trade is None:
            return
        self.last_trade_at = time.time()
        # Kuyruk işçileri gecikmiş sinyali ayıklayabilsin.
        try:
            trade.raw = dict(trade.raw or {})
            trade.raw["_received_at"] = time.time()
        except Exception:  # noqa: BLE001
            pass

        if strategy == "ai":
            # AI Trade: copy/cüzdan olayı yok; yalnızca token fırsatı sayılan BUY
            # event'leri işlenir. Cüzdan keşfi ve tracked sell burada durur.
            if trade.side == "buy":
                if await self._drop_stale_ai_token_if_needed(ws, trade.mint):
                    return
                if not self._ai_signal_cooldown_ok(trade.mint):
                    return
                trade.raw["_strategy"] = "ai"
                await self._enqueue_trade(trade)
            return

        # COPY Trade: takipteki cüzdan işlemi -> bildirim + işlem akışı.
        if trade.trader in self.tracked:
            await self._enqueue_trade(trade)
        elif settings.discovery_enabled and trade.side == "buy":
            self._record_buyer(trade.trader, trade.mint)

    def _handle_tracked(self, trade):
        db = SessionLocal()
        try:
            handle_trade_event(db, trade, notifier=self.notifier, signer=self.signer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Takip olayı işlenemedi: %s", exc)
        finally:
            db.close()

    def _record_buyer(self, trader: str, mint: str):
        if trader in self.known_candidates or trader in self.tracked:
            return
        hits = self.buyer_hits.setdefault(trader, set())
        hits.add(mint)
        if len(hits) >= settings.discovery_min_token_hits:
            self.known_candidates.add(trader)
            self.buyer_hits.pop(trader, None)
            asyncio.create_task(asyncio.to_thread(self._persist_candidate, trader))
        # bellek koruması
        if len(self.buyer_hits) > 20000:
            self.buyer_hits.clear()
        if len(self.known_candidates) > 50000:
            self.known_candidates.clear()

    def _persist_candidate(self, trader: str):
        db = SessionLocal()
        try:
            if record_candidate(db, trader, source="auto-pumpportal"):
                logger.info("Yeni aday cüzdan keşfedildi: %s", trader)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aday kaydedilemedi: %s", exc)
        finally:
            db.close()

    def _audit(self, level: str, message: str, context: dict | None = None) -> None:
        """Panel Loglar sayfasına görünür listener/AI-scan kaydı yaz.

        Python logger satırları yalnızca docker logs'a düşer. Kullanıcı panelde
        "hiç log gelmiyor" dediğinde asıl sorun çoğu zaman buy/sell kararı
        üretilmemesi değil, listener sağlık bilgisinin DB audit log'a yazılmamasıdır.
        Bu helper WebSocket'in canlı/sessiz/yeniden bağlanıyor durumunu panelde de
        görünür yapar.
        """
        db = SessionLocal()
        try:
            db.add(AuditLog(level=level, category="ai_scan", message=message, context=context or {}))
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    async def _audit_async(self, level: str, message: str, context: dict | None = None) -> None:
        await asyncio.to_thread(self._audit, level, message, context)

    async def _audit_scan_status(self, force: bool = False) -> None:
        now = time.time()
        qsize = self.event_queue.qsize() if self.event_queue is not None else 0
        raw_age = int(now - self.last_raw_at) if self.last_raw_at else -1
        new_age = int(now - self.last_new_token_at) if self.last_new_token_at else -1
        trade_age = int(now - self.last_trade_at) if self.last_trade_at else -1
        idle_limit = int(getattr(settings, "pumpportal_idle_reconnect_seconds", 90) or 90)
        ctx = {
            "watched": len(self.watched_tokens),
            "queue": qsize,
            "queued": self.stat_queued,
            "processed": self.stat_processed,
            "dropped": self.stat_dropped,
            "stale": self.stat_drop_stale,
            "workers": int(settings.ai_signal_workers),
            "raw_age_seconds": raw_age,
            "new_token_age_seconds": new_age,
            "trade_age_seconds": trade_age,
            "reconnect": self.last_reconnect_reason or "-",
            "strategy": _strategy_mode(),
        }
        # Normal nabız: 60 sn'de bir. Sessizlik/bozulma: 30 sn'de bir uyarı.
        silent = raw_age >= idle_limit if raw_age >= 0 else False
        if silent:
            if force or now - self.last_warning_audit_at >= 30:
                self.last_warning_audit_at = now
                await self._audit_async(
                    "warning",
                    f"AI token akışı sessiz: {raw_age}s ham mesaj yok; reconnect deneniyor",
                    ctx,
                )
            return

        # TRADE ABONELİĞİ TEŞHİSİ (kritik): yeni-token akışı CANLI ama hiç trade
        # event'i YOK. PumpPortal kuralı: subscribeNewToken anahtarsız çalışır, ama
        # subscribeTokenTrade/AccountTrade FUNDED API anahtarı (cüzdan ≥0.02 SOL)
        # ister. Anahtar yoksa/bakiye düşükse yalnız yeni-token gelir → AI hiç token
        # trade'i görmez, copy gerçek-zamanlı çalışmaz (yalnız yavaş RPC poll kalır).
        # Bu sessiz starvasyonu "akış aktif" diye göstermek yerine NET uyarıya çeviririz.
        trade_stream_dead = (
            len(self.watched_tokens) >= 10       # birçok tokene trade aboneliği yapıldı
            and self.last_trade_at == 0.0        # ama HİÇ trade event'i gelmedi
            and new_age >= 0                     # yeni-token akışı ise canlı
        )
        if trade_stream_dead:
            ctx["trade_stream"] = "dead"
            ctx["hint"] = (
                "PumpPortal trade aboneliği çalışmıyor: subscribeTokenTrade/AccountTrade "
                "için funded API anahtarı (cüzdan ≥0.02 SOL) gerekir. Anahtar yok veya "
                "bakiye düşükse yalnızca yeni-token akışı gelir; AI token trade'i görmez, "
                "copy gerçek-zamanlı tetiklenmez."
            )
            if force or now - self.last_warning_audit_at >= 60:
                self.last_warning_audit_at = now
                await self._audit_async(
                    "warning",
                    f"Trade akışı YOK — {len(self.watched_tokens)} token izleniyor ama hiç "
                    f"trade event'i gelmedi. PumpPortal funded API anahtarı (≥0.02 SOL) gerekli "
                    f"veya bakiyeyi kontrol et.",
                    ctx,
                )
            return
        if force or now - self.last_audit_at >= 60:
            self.last_audit_at = now
            await self._audit_async(
                "info",
                f"AI token akışı aktif — watched={len(self.watched_tokens)} queue={qsize} processed={self.stat_processed} raw_age={raw_age}s",
                ctx,
            )

    async def _queue_stats_loop(self):
        while True:
            try:
                # Sağlık ekranındaki "Dinleyici bağlı" bilgisini PumpPortal için de
                # güncel tut. Önceden bu heartbeat yalnızca Helius listener'da vardı.
                await asyncio.to_thread(self._heartbeat)
                qsize = self.event_queue.qsize() if self.event_queue is not None else 0
                now = time.time()
                raw_age = int(now - self.last_raw_at) if self.last_raw_at else -1
                new_age = int(now - self.last_new_token_at) if self.last_new_token_at else -1
                trade_age = int(now - self.last_trade_at) if self.last_trade_at else -1
                logger.info(
                    "[AI-SCAN] watched=%d queue=%d queued=%d processed=%d dropped=%d stale=%d workers=%d raw_age=%ss new_token_age=%ss trade_age=%ss reconnect=%s",
                    len(self.watched_tokens), qsize, self.stat_queued, self.stat_processed,
                    self.stat_dropped, self.stat_drop_stale, int(settings.ai_signal_workers),
                    raw_age, new_age, trade_age, self.last_reconnect_reason or "-",
                )
                await self._audit_scan_status()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(15)

    async def _idle_reconnect_watchdog(self, ws):
        """PumpPortal bağlantısı sessiz kalırsa yeniden bağlan.

        Bazı durumlarda WS TCP olarak açık kalıp panelde "Online" görünür ama
        yeni token/trade mesajı akmaz. Pump.fun tarafında dakikalarca hiç mesaj
        gelmemesi normal değildir; bu durumda bağlantıyı kapatıp run() döngüsünün
        temiz reconnect yapmasını sağlarız.
        """
        idle_limit = int(getattr(settings, "pumpportal_idle_reconnect_seconds", 90) or 0)
        if idle_limit <= 0:
            return
        while True:
            await asyncio.sleep(max(10, min(30, idle_limit // 3 or 10)))
            last = self.last_raw_at or time.time()
            idle = time.time() - last
            if idle > idle_limit:
                self.last_reconnect_reason = f"idle>{idle_limit}s"
                logger.warning("PumpPortal akışı sessiz kaldı: %.0fs mesaj yok, reconnect tetikleniyor", idle)
                await self._audit_scan_status(force=True)
                try:
                    await ws.close(code=1000, reason="idle reconnect")
                except Exception:  # noqa: BLE001
                    pass
                return

    def _heartbeat(self):
        db = SessionLocal()
        try:
            from ..services.settings_service import set_heartbeat
            set_heartbeat(db)
        except Exception:  # noqa: BLE001
            pass
        finally:
            db.close()

    def _ws_url(self) -> str:
        """Veri akışı URL'i. subscribeTokenTrade/AccountTrade için API anahtarı şart
        (PumpPortal kuralı: funded ≥0.02 SOL). Anahtar varsa URL'e eklenir."""
        url = settings.pumpportal_data_ws
        if settings.pumpportal_api_key:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}api-key={settings.pumpportal_api_key}"
        logger.warning(
            "PumpPortal API anahtarı yok: yalnızca yeni-token akışı çalışır. "
            "Keşif (token trade) ve takip (account trade) için, cüzdanında ≥0.02 SOL "
            "bulunan bir PUMPPORTAL_API_KEY gerekir."
        )
        return url

    async def run(self, stop_event: asyncio.Event | None = None):
        import websockets

        ws_url = self._ws_url()
        self.event_queue = asyncio.Queue(maxsize=max(100, int(settings.ai_signal_queue_size)))
        worker_count = max(1, min(int(settings.ai_signal_workers), 32))
        workers = [asyncio.create_task(self._event_worker(i + 1)) for i in range(worker_count)]
        stats_task = asyncio.create_task(self._queue_stats_loop())
        backoff = 1.0
        try:
            while stop_event is None or not stop_event.is_set():
                self.subscribed_accounts.clear()
                self.watched_tokens.clear()
                try:
                    async with websockets.connect(ws_url, ping_interval=20, max_queue=4096) as ws:
                        strategy = _strategy_mode()
                        logger.info(
                            "PumpPortal veri akışına bağlanıldı (keşif=%s, strateji=%s, anahtar=%s, workers=%d, watched_cap=%d)",
                            settings.discovery_enabled, strategy, bool(settings.pumpportal_api_key),
                            worker_count, int(settings.discovery_max_watched_tokens),
                        )
                        await self._audit_async(
                            "info",
                            "PumpPortal dinleyici bağlandı; yeni token aboneliği hazırlanıyor",
                            {
                                "strategy": strategy,
                                "discovery_enabled": bool(settings.discovery_enabled),
                                "has_api_key": bool(settings.pumpportal_api_key),
                                "workers": worker_count,
                                "watched_cap": int(settings.discovery_max_watched_tokens),
                            },
                        )
                        backoff = 1.0
                        self.last_raw_at = time.time()
                        self.last_new_token_at = 0.0
                        self.last_trade_at = 0.0
                        self.last_reconnect_reason = ""
                        if settings.discovery_enabled or strategy == "ai":
                            await ws.send(json.dumps({"method": "subscribeNewToken"}))
                            await self._audit_async(
                                "info",
                                "PumpPortal subscribeNewToken gönderildi; yeni token akışı bekleniyor",
                                {"strategy": strategy, "provider": "pumpportal"},
                            )
                        refresher = asyncio.create_task(self._refresh_accounts(ws))
                        idle_watchdog = asyncio.create_task(self._idle_reconnect_watchdog(ws))
                        try:
                            async for raw in ws:
                                if stop_event is not None and stop_event.is_set():
                                    break
                                await self.process(ws, raw)
                        finally:
                            refresher.cancel()
                            idle_watchdog.cancel()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("PumpPortal bağlantısı koptu (%.0fs sonra tekrar): %s", backoff, exc)
                    await self._audit_async(
                        "warning",
                        f"PumpPortal bağlantısı koptu; {backoff:.0f}s sonra yeniden denenecek",
                        {"error": str(exc)[:240], "backoff_seconds": backoff, "provider": "pumpportal"},
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
        finally:
            stats_task.cancel()
            for w in workers:
                w.cancel()


async def run_pumpportal_listener(stop_event: asyncio.Event | None = None) -> None:
    signer = PumpPortalTrader() if settings.pumpportal_api_key else None
    await PumpPortalListener(signer=signer).run(stop_event)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from ..security.logging_filters import install_redaction
    install_redaction()
    if not settings.live_listener_enabled:
        logger.info("Canlı dinleyici kapalı (LIVE_LISTENER_ENABLED=false)")
        return
    asyncio.run(run_pumpportal_listener())


if __name__ == "__main__":
    main()

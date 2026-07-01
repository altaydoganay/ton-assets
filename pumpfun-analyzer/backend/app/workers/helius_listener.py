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


def _strategy_mode() -> str:
    """Aktif motor: 'ai' veya 'copy' (DB risk ayarından)."""
    db = SessionLocal()
    try:
        from ..services.settings_service import get_setting
        risk = get_setting(db, "risk")
        return "ai" if str(risk.get("strategy_mode", "copy") or "copy").lower() == "ai" else "copy"
    except Exception:  # noqa: BLE001
        return "copy"
    finally:
        db.close()


def build_ai_trades(ntx) -> list[PumpPortalTrade]:
    """A1: keşif firehose'undaki bir işlemden AI sinyali olacak TAZE token ALIMLARINI
    çıkar. AI modunda lider aranmaz; her buy bir token-fırsatıdır. handle_trade_event'in
    is_ai_signal yolu tokeni değerlendirir (yaş/skor/fiyat/fail-safe kapıları orada).

    Böylece AI Trade, PumpPortal firehose'u OLMADAN, Helius/Chainstack WS
    (logsSubscribe) üzerinden çalışır — SOL yakmadan (RPC kredisi)."""
    out: list[PumpPortalTrade] = []
    for wallet, mint in extract_buyers(ntx):
        swap = detect_swap(ntx, wallet)
        if swap is None or swap.side != "buy":
            continue
        out.append(PumpPortalTrade(
            signature=swap.signature, trader=wallet, mint=mint, side="buy",
            sol_amount=swap.sol_amount, token_amount=swap.token_amount,
            pool=swap.venue, market_cap_sol=None, raw={"_strategy": "ai", "_source": "helius-ws"},
        ))
    return out


def _resolve_logs_mode() -> str:
    """Etkin WS logsSubscribe modu: 'mentions' veya 'all'."""
    m = (settings.ws_logs_mode or "auto").lower()
    if m in ("mentions", "all"):
        return m
    # auto: Helius (mentions'ı destekler) → mentions; aksi (Chainstack/standart) → all
    return "mentions" if settings.helius_api_key else "all"


def logs_mention_pumpfun(logs) -> bool:
    """'all' akışındaki bir log bildiriminde pump.fun/pumpswap programı geçiyor mu?

    getTransaction'a GİTMEDEN ucuz ön-eleme (Chainstack 'all' modunda tüm Solana
    logları gelir; sadece pump.fun'ları getTransaction'a alırız — kredi koruması)."""
    if not logs:
        return False
    for line in logs:
        if PUMP_FUN_PROGRAM in line or PUMP_SWAP_PROGRAM in line:
            return True
    return False


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
        # A1: AI modu durumu + token başına cooldown (aynı tokeni her trade'de tekrar
        # değerlendirip boşa RPC/CPU harcamamak için). strategy_mode _refresh'te tazelenir.
        self.strategy_mode = "copy"
        self._ai_last_by_mint: dict[str, float] = {}
        self.stat_ai_signals = 0
        # WS logsSubscribe modu: 'mentions' (Helius) veya 'all' (Chainstack/standart).
        # 'all' modunda tek firehose aboneliği + client-side pump.fun filtresi ile
        # copy+AI+keşif beslenir (Chainstack mentions'ı desteklemediği için).
        self.logs_mode = "mentions"
        self.tracked_set: set[str] = set()

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

    async def _subscribe_firehose(self, ws):
        """'all' modu: tek logsSubscribe['all'] aboneliği (Chainstack uyumlu).
        pump.fun filtresi client-side yapılır (process → logs_mention_pumpfun)."""
        rid = self._next_id()
        self.pending[rid] = ("firehose", None)
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": "logsSubscribe",
            "params": ["all", {"commitment": "confirmed"}],
        }))

    async def _unsubscribe_kind(self, ws, kind: str):
        for sid in [s for s, (k, _w) in list(self.sub_meta.items()) if k == kind]:
            try:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": self._next_id(),
                                          "method": "logsUnsubscribe", "params": [sid]}))
            except Exception:  # noqa: BLE001
                pass
            self.sub_meta.pop(sid, None)

    async def _refresh(self, ws):
        listener_was_on = True
        while True:
            try:
                await asyncio.to_thread(self._heartbeat)
                # ASCII etiketli durum logu (Windows findstr ile aranabilir)
                logger.info("[DISCOVERY] lookups=%d candidates=%d tracked_subs=%d ai_signals=%d mode=%s",
                            self.stat_lookups, self.stat_candidates, len(self.subscribed_accounts),
                            self.stat_ai_signals, self.strategy_mode)
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
                # A1: AI modunda firehose ZORUNLU (AI token-fırsat evreni oradan gelir).
                self.strategy_mode = await asyncio.to_thread(_strategy_mode)
                self.logs_mode = _resolve_logs_mode()
                self.tracked_set = set(_tracked_addresses())
                want_discovery = (await asyncio.to_thread(_discovery_on)) or self.strategy_mode == "ai"

                if self.logs_mode == "all":
                    # CHAINSTACK/STANDART: mentions çalışmaz → tek 'all' firehose +
                    # client-side pump.fun filtresi. copy + AI + keşif hepsi buradan.
                    need = want_discovery or self.strategy_mode == "ai" or bool(self.tracked_set)
                    if need and not self.discovery_sub_active:
                        await self._subscribe_firehose(ws)
                        self.discovery_sub_active = True
                        logger.info("[LISTENER] 'all' firehose AÇIK (mentions desteklenmeyen node — client-side pump.fun filtresi)")
                    elif not need and self.discovery_sub_active:
                        await self._unsubscribe_kind(ws, "firehose")
                        self.discovery_sub_active = False
                        logger.info("[LISTENER] 'all' firehose KAPALI")
                else:
                    # HELIUS: mentions modu (adres filtreli, düşük bant genişliği).
                    if want_discovery and not self.discovery_sub_active:
                        await self._subscribe_logs(ws, PUMP_FUN_PROGRAM, "discovery", None)
                        self.discovery_sub_active = True
                        await self._subscribe_logs(ws, PUMP_SWAP_PROGRAM, "discovery", None)
                        logger.info("[LISTENER] keşif akışı AÇIK (pump.fun firehose)")
                    elif not want_discovery and self.discovery_sub_active:
                        await self._unsubscribe_kind(ws, "discovery")
                        self.discovery_sub_active = False
                        logger.info("[LISTENER] keşif akışı KAPALI (firehose durduruldu — kredi koruması)")
                    for addr in self.tracked_set - self.subscribed_accounts:
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
        elif kind == "firehose":
            # 'all' modu: ÖNCE ucuz log filtresi (pump.fun mı?), sonra rate-limited
            # getTransaction. Tüm Solana logları gelir; sadece pump.fun'ları işleriz.
            logs = value.get("logs") or []
            if logs_mention_pumpfun(logs) and self.limiter.allow():
                await asyncio.to_thread(self._handle_firehose, sig)

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

    def _ai_cooldown_ok(self, mint: str) -> bool:
        """Aynı tokeni cooldown içinde tekrar AI'a yollama (RPC/CPU koruması)."""
        cooldown = float(settings.ai_signal_token_cooldown_seconds or 0)
        if cooldown <= 0:
            return True
        now = time.monotonic()
        last = self._ai_last_by_mint.get(mint, 0.0)
        if now - last < cooldown:
            return False
        self._ai_last_by_mint[mint] = now
        if len(self._ai_last_by_mint) > 20000:  # bellek koruması
            cutoff = now - max(60.0, cooldown * 20)
            self._ai_last_by_mint = {k: v for k, v in self._ai_last_by_mint.items() if v >= cutoff}
        return True

    def _handle_discovery(self, sig: str):
        self.stat_lookups += 1
        try:
            ntx = self._fetch_ntx(sig)
            if ntx is None:
                return
            for wallet, mint in extract_buyers(ntx):
                self._record_buyer(wallet, mint)
            # A1: AI modunda aynı firehose'daki taze token alımlarını AI motoruna da
            # yönlendir (PumpPortal'sız AI). Keşif kaydı yukarıda korunur.
            if self.strategy_mode == "ai":
                self._route_ai_signals(ntx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DISCOVERY] olay atlandı: %s", exc)

    def _handle_firehose(self, sig: str):
        """'all' modu: pump.fun işlemini işle → keşif + (AI veya copy) yönlendir.

        mentions çalışmayan node'larda (Chainstack) copy da AI da buradan beslenir:
        firehose'daki her pump.fun alımı → keşif aday kaydı; AI modunda AI sinyali;
        copy modunda alıcı/satıcı TAKİPTEyse copy sinyali."""
        self.stat_lookups += 1
        try:
            ntx = self._fetch_ntx(sig)
            if ntx is None:
                return
            for wallet, mint in extract_buyers(ntx):
                self._record_buyer(wallet, mint)
            if self.strategy_mode == "ai":
                self._route_ai_signals(ntx)
            else:
                self._route_copy_signals(ntx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[FIREHOSE] olay atlandı: %s", exc)

    def _route_copy_signals(self, ntx):
        """Firehose'daki TAKİP EDİLEN cüzdan swap'larını (alım+satım) copy motoruna
        yönlendir. 'all' modunda per-wallet mentions çalışmadığından copy buradan gelir."""
        involved = set(ntx.sol_deltas.keys()) | {o for (o, _m) in ntx.token_deltas.keys()}
        leaders = involved & self.tracked_set
        if not leaders:
            return
        db = SessionLocal()
        try:
            for wallet in leaders:
                swap = detect_swap(ntx, wallet)
                if swap is None:
                    continue
                trade = PumpPortalTrade(
                    signature=swap.signature, trader=wallet, mint=swap.token_mint,
                    side=swap.side, sol_amount=swap.sol_amount, token_amount=swap.token_amount,
                    pool=swap.venue, market_cap_sol=None, raw={},
                )
                try:
                    handle_trade_event(db, trade, chain=self.chain,
                                       notifier=self.notifier, signer=self.signer)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[FIREHOSE-COPY] işlenemedi %s: %s", wallet[:6], exc)
        finally:
            db.close()

    def _route_ai_signals(self, ntx):
        trades = build_ai_trades(ntx)
        if not trades:
            return
        db = SessionLocal()
        try:
            for trade in trades:
                if not self._ai_cooldown_ok(trade.mint):
                    continue
                try:
                    res = handle_trade_event(db, trade, chain=self.chain,
                                             notifier=self.notifier, signer=self.signer)
                    self.stat_ai_signals += 1
                    if res.get("action") == "buy" and res.get("traded"):
                        logger.info("[AI-WS] alım açıldı %s", trade.mint[:8])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AI-WS] sinyal işlenemedi %s: %s", trade.mint[:8], exc)
        finally:
            db.close()

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

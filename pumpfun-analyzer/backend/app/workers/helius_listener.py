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
    WSOL_MINT,
    detect_swap,
    extract_buyers,
)
from ..models import Token, Wallet, WalletStatus
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


def _ws_urls() -> list[str]:
    """Birincil + yedek WS adresleri (tekrarsız).

    Birincil reddederse (örn. Chainstack aylık kota → HTTP 403) run() sıradakine
    döner. Public yedek blockSubscribe vermez ama logsSubscribe(mentions) İLETİR;
    mod merdiveni (block→mentions→all) bunu otomatik ele alır."""
    urls = [_ws_url()]
    for fb in (settings.solana_ws_fallback_url or "").split(","):
        fb = fb.strip()
        if fb and fb not in urls:
            urls.append(fb)
    return urls


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
    """Etkin WS abonelik modu: 'mentions', 'block' veya 'all'."""
    m = (settings.ws_logs_mode or "auto").lower()
    if m in ("mentions", "all", "block"):
        return m
    # auto: Helius (mentions destekler) → mentions; aksi (Chainstack/standart) →
    # block (sunucu filtreli + tx gömülü = en ucuz/en hızlı; başarısızsa
    # çalışma anında 'all'e düşülür).
    return "mentions" if settings.helius_api_key else "block"


def block_txs_from_notification(msg: dict) -> list[dict]:
    """blockNotification'dan getTransaction-uyumlu ham tx sözlükleri çıkar.

    blockSubscribe(transactionDetails=full) her eşleşen işlemi {transaction, meta}
    olarak GÖMÜLÜ verir; blockTime/slot blok seviyesindedir. normalize_rpc_transaction
    getTransaction şekli beklediği için blockTime/slot'u tx'e taşırız. Başarısız
    (meta.err) işlemler elenir. → pump.fun için getTransaction ÇAĞRISI GEREKMEZ."""
    value = (((msg.get("params") or {}).get("result")) or {}).get("value") or {}
    blk = value.get("block") or {}
    slot = value.get("slot")
    btime = blk.get("blockTime") or 0
    out: list[dict] = []
    for entry in (blk.get("transactions") or []):
        meta = entry.get("meta") or {}
        if meta.get("err") is not None:
            continue
        raw = dict(entry)
        raw["blockTime"] = btime
        raw["slot"] = slot
        out.append(raw)
    return out


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


def logs_is_pumpfun_create(logs) -> bool:
    """Bu bildirim YENİ TOKEN oluşturma (pump.fun 'Create') mı?

    Launch'ı en erken yakalamak kritik: create işlemleri trade'lerden çok daha
    NADİRDİR, bu yüzden bunları rate-limit'i AŞARAK işleriz (launch'ları örnekleme
    sınırına kurban etmeyiz). Create tx'i genelde dev'in ilk alımını da içerir →
    AI token'ı t≈0'da değerlendirir. Bu, 'veri geç geliyor / token'ı 19 dk sonra
    aldı' sorununun ana çözümüdür."""
    if not logs:
        return False
    for line in logs:
        if "Instruction: Create" in line:
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
        self.stat_creates = 0   # yakalanan yeni-token (Create) sayısı
        # MIGRATION YAKINLIĞI: mint başına gözlenen NET SOL girişi (alım - satım).
        # pump.fun bonding curve ~85 SOL dolunca PumpSwap'a mezun olur; bu tahmin
        # AI sinyaline eklenir (curve_sol_est) — token'ın mezuniyete ne kadar
        # yaklaştığının ucuz, akıştan-türetilmiş göstergesi.
        self.curve_sol: "OrderedDict[str, float]" = OrderedDict()
        # WS logsSubscribe modu: 'mentions' (Helius) veya 'all' (Chainstack/standart).
        # 'all' modunda tek firehose aboneliği + client-side pump.fun filtresi ile
        # copy+AI+keşif beslenir (Chainstack mentions'ı desteklemediği için).
        self.logs_mode = "mentions"
        self.tracked_set: set[str] = set()
        # block modu çalışma anında başarısız olursa (node desteklemiyor) 'all'e düş.
        self.block_failed = False
        # OLAY KUYRUĞU + PARALEL WORKER'lar: process() içinde her tx için ağ
        # çağrısını (assess_token 1-3 sn) sırayla AWAIT etmek WS okuma döngüsünü
        # BLOKLAR — akış dakikalarca geri kalır ("10 dakikada 5 token" belirtisi).
        # Okuma döngüsü yalnızca kuyruğa koyar; worker'lar paralel işler.
        self.event_queue: asyncio.Queue | None = None
        self.stat_q_dropped = 0     # kuyruk doluyken atılan olay
        self.stat_drop_stale = 0    # bayatladığı için işlenmeyen olay
        # Yedek WS'e düşüldü mü (birincil 403/kota vb.)? Mod merdiveni buna bakar:
        # public yedek mentions İLETİR → block başarısızsa fallback'te mentions seç.
        self.on_fallback_ws = False

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

    async def _subscribe_block(self, ws):
        """'block' modu: blockSubscribe(mentionsAccountOrProgram=pump.fun, full).

        Sunucu yalnız pump.fun içeren blokları, İÇİNDE YALNIZ EŞLEŞEN işlemler
        meta'sıyla gömülü olarak yollar → getTransaction gerekmez, "all"e göre
        ~100× az bildirim (kredi) ve daha düşük gecikme (ek RTT yok)."""
        rid = self._next_id()
        self.pending[rid] = ("blockfire", None)
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": "blockSubscribe",
            "params": [
                {"mentionsAccountOrProgram": PUMP_FUN_PROGRAM},
                {"commitment": "confirmed", "encoding": "jsonParsed",
                 "transactionDetails": "full", "showRewards": False,
                 "maxSupportedTransactionVersion": 0},
            ],
        }))

    async def _unsubscribe_kind(self, ws, kind: str):
        method = "blockUnsubscribe" if kind == "blockfire" else "logsUnsubscribe"
        for sid in [s for s, (k, _w) in list(self.sub_meta.items()) if k == kind]:
            try:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": self._next_id(),
                                          "method": method, "params": [sid]}))
            except Exception:  # noqa: BLE001
                pass
            self.sub_meta.pop(sid, None)

    async def _refresh(self, ws):
        listener_was_on = True
        while True:
            try:
                await asyncio.to_thread(self._heartbeat)
                # ASCII etiketli durum logu (Windows findstr ile aranabilir)
                qsize = self.event_queue.qsize() if self.event_queue is not None else 0
                logger.info("[DISCOVERY] lookups=%d candidates=%d tracked_subs=%d ai_signals=%d creates=%d "
                            "queue=%d q_dropped=%d stale=%d mode=%s ws_mode=%s",
                            self.stat_lookups, self.stat_candidates, len(self.subscribed_accounts),
                            self.stat_ai_signals, self.stat_creates,
                            qsize, self.stat_q_dropped, self.stat_drop_stale,
                            self.strategy_mode, self.logs_mode)
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
                if self.logs_mode == "block" and self.block_failed:
                    # MOD MERDİVENİ: public yedek mentions İLETİR (canlı doğrulandı)
                    # → orada mentions; birincilde (Chainstack mentions sessiz) all.
                    self.logs_mode = "mentions" if self.on_fallback_ws else "all"
                self.tracked_set = set(_tracked_addresses())
                want_discovery = (await asyncio.to_thread(_discovery_on)) or self.strategy_mode == "ai"

                if self.logs_mode == "block":
                    # CHAINSTACK (tercih): sunucu filtreli pump.fun blok akışı; tx
                    # gömülü gelir. copy + AI + keşif hepsi buradan, getTransaction'sız.
                    need = want_discovery or self.strategy_mode == "ai" or bool(self.tracked_set)
                    if need and not self.discovery_sub_active:
                        await self._subscribe_block(ws)
                        self.discovery_sub_active = True
                        logger.info("[LISTENER] blockSubscribe AÇIK (pump.fun sunucu-filtreli, tx gömülü — getTransaction yok)")
                    elif not need and self.discovery_sub_active:
                        await self._unsubscribe_kind(ws, "blockfire")
                        self.discovery_sub_active = False
                        logger.info("[LISTENER] blockSubscribe KAPALI")
                elif self.logs_mode == "all":
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
        # abonelik HATASI: block modu desteklenmiyorsa 'all'e otomatik düş.
        if "error" in msg and "id" in msg:
            meta = self.pending.pop(msg["id"], None)
            if meta and meta[0] == "blockfire":
                self.block_failed = True
                self.discovery_sub_active = False
                logger.warning("blockSubscribe reddedildi (%s) — 'all' moduna düşülüyor", msg.get("error"))
            return
        if msg.get("method") == "blockNotification":
            # 'block' modu: eşleşen pump.fun işlemleri meta'sıyla GÖMÜLÜ geldi.
            for raw_tx in block_txs_from_notification(msg):
                logs = (raw_tx.get("meta") or {}).get("logMessages") or []
                is_create = logs_is_pumpfun_create(logs)
                if is_create:
                    self.stat_creates += 1
                # Create HER ZAMAN işlenir (launch anı); copy modunda takip filtresi
                # zaten client-side ucuz. AI'da sıradan trade'ler değerlendirme
                # bütçesiyle (assess_token zincir/piyasa çağrıları) örneklenir.
                if is_create or self.strategy_mode != "ai" or self.limiter.allow():
                    self._enqueue(self._handle_block_tx, (raw_tx, is_create), is_create)
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
            self._enqueue(self._handle_tracked, (sig, wallet), is_create=True)  # takip olayı asla bayatlamasın
        elif kind == "discovery":
            # Yeni-token (Create) limiti AŞAR — launch'lar örneklemeye kurban gitmesin.
            logs = value.get("logs") or []
            is_create = logs_is_pumpfun_create(logs)
            if is_create:
                self.stat_creates += 1
            if is_create or self.limiter.allow():
                self._enqueue(self._handle_discovery, (sig,), is_create)
            # limit aşıldıysa bu keşif olayını düşür (kredi koruması)
        elif kind == "firehose":
            # 'all' modu: ÖNCE ucuz log filtresi (pump.fun mı?), sonra rate-limited
            # getTransaction. Tüm Solana logları gelir; sadece pump.fun'ları işleriz.
            logs = value.get("logs") or []
            if logs_mention_pumpfun(logs):
                # YENİ TOKEN (Create) rate-limit'i AŞAR → launch'ı geç yakalamayalım.
                # Sıradan trade'ler örnekleme limitine tabidir (kredi koruması).
                is_create = logs_is_pumpfun_create(logs)
                if is_create:
                    self.stat_creates += 1
                if is_create or self.limiter.allow():
                    self._enqueue(self._handle_firehose, (sig,), is_create)

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

    def _enqueue(self, fn, args: tuple, is_create: bool = False) -> None:
        """Olayı worker kuyruğuna at (okuma döngüsünü BLOKLAMADAN).

        Kuyruk doluysa en eski sıradan olayı düşür, yenisini al (taze veri
        değerlidir). Create olayları her zaman sığdırılır."""
        if self.event_queue is None:
            return
        item = (fn, args, time.time(), is_create)
        try:
            self.event_queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self.event_queue.get_nowait()
                self.event_queue.task_done()
                self.stat_q_dropped += 1
                self.event_queue.put_nowait(item)
            except Exception:  # noqa: BLE001
                self.stat_q_dropped += 1

    async def _event_worker(self, idx: int):
        assert self.event_queue is not None
        while True:
            fn, args, enq_t, is_create = await self.event_queue.get()
            try:
                # Bayat sıradan olayı işleme (geç girişe zemin olur); create'ler
                # her zaman işlenir (launch anı — token kaydı/yaş için kritik).
                if not is_create and (time.time() - enq_t) > 30.0:
                    self.stat_drop_stale += 1
                    continue
                await asyncio.to_thread(fn, *args)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Olay worker-%d hata: %s", idx, exc)
            finally:
                self.event_queue.task_done()

    def _update_curve(self, ntx) -> None:
        """Akıştan mint başına NET SOL girişini biriktir (migration yakınlığı tahmini)."""
        for (owner, mint), amt in (ntx.token_deltas or {}).items():
            if mint == WSOL_MINT:
                continue
            sol = float((ntx.sol_deltas or {}).get(owner, 0.0))
            if amt > 0 and sol < 0:      # alım: SOL curve'e girdi
                self.curve_sol[mint] = self.curve_sol.get(mint, 0.0) - sol
            elif amt < 0 and sol > 0:    # satım: SOL curve'den çıktı
                self.curve_sol[mint] = self.curve_sol.get(mint, 0.0) - sol
            self.curve_sol.move_to_end(mint, last=True)
        while len(self.curve_sol) > 20000:  # bellek koruması (en eskiyi at)
            self.curve_sol.popitem(last=False)

    def _mark_created(self, ntx) -> None:
        """Create tx'inden GERÇEK oluşturma zamanını token'a yaz.

        Yaş kapısı artık tahmine (first_seen/pair) değil zincirdeki gerçek create
        zamanına dayanır — 'token eski/çok yeni' kararları kesinleşir."""
        from datetime import datetime, timezone
        mints = {m for (_o, m) in (ntx.token_deltas or {}).keys() if m != WSOL_MINT}
        if not mints or not ntx.block_time:
            return
        created = datetime.fromtimestamp(int(ntx.block_time), tz=timezone.utc)
        db = SessionLocal()
        try:
            from ..services.analysis_service import get_or_create_token
            for mint in mints:
                token = get_or_create_token(db, mint)
                if token.created_on_chain_at is None:
                    token.created_on_chain_at = created
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("create zamanı yazılamadı: %s", exc)
        finally:
            db.close()

    def _handle_block_tx(self, raw_tx: dict, is_create: bool = False):
        """'block' modu: GÖMÜLÜ gelen işlemi işle (getTransaction YOK → 0 ek RPC).
        Keşif aday kaydı + (AI veya copy) yönlendirme — _handle_firehose ile aynı
        akış, sadece ağ çağrısı olmadan."""
        self.stat_lookups += 1
        try:
            ntx = normalize_rpc_transaction(raw_tx)
            if ntx is None:
                return
            self._update_curve(ntx)
            if is_create:
                self._mark_created(ntx)
            for wallet, mint in extract_buyers(ntx):
                self._record_buyer(wallet, mint)
            if self.strategy_mode == "ai":
                self._route_ai_signals(ntx)
            else:
                self._route_copy_signals(ntx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BLOCKFIRE] olay atlandı: %s", exc)

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
                curve = round(float(self.curve_sol.get(trade.mint, 0.0)), 3)
                trade.raw["_curve_sol_est"] = curve  # migration yakınlığı tahmini
                try:
                    res = handle_trade_event(db, trade, chain=self.chain,
                                             notifier=self.notifier, signer=self.signer)
                    self.stat_ai_signals += 1
                    # curve tahminini token'a işle (panel + skorlama okuyabilsin)
                    if curve > 0:
                        tok = db.query(Token).filter(Token.mint == trade.mint).first()
                        if tok is not None:
                            tok.metrics = {**(tok.metrics or {}), "curve_sol_est": curve}
                            db.commit()
                    if res.get("action") == "buy" and res.get("traded"):
                        logger.info("[AI-WS] alım açıldı %s (curve≈%.1f SOL)", trade.mint[:8], curve)
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

        urls = _ws_urls()
        if not settings.helius_api_key and "api-key" not in urls[0]:
            logger.warning("Helius API anahtarı yok; dinleyici sınırlı çalışır.")
        url_idx = 0  # bağlantı hatasında sıradakine döner; başarıda birincile sıfırlanır
        # Paralel işleme: okuma döngüsü yalnız kuyruğa yazar, worker'lar işler.
        # (Aksi halde her tx'in 1-3 sn'lik analizi WS okumasını bloklar ve akış
        # dakikalarca geri kalırdı — "10 dakikada 5 token" belirtisi.)
        self.event_queue = asyncio.Queue(maxsize=max(100, int(getattr(settings, "ai_signal_queue_size", 500))))
        worker_count = max(1, min(int(getattr(settings, "ai_signal_workers", 8)), 32))
        workers = [asyncio.create_task(self._event_worker(i + 1)) for i in range(worker_count)]
        backoff = 1.0
        try:
            while stop_event is None or not stop_event.is_set():
                self.sub_meta.clear()
                self.pending.clear()
                self.subscribed_accounts.clear()
                self.discovery_sub_active = False
                # Geçici bir hata blockSubscribe'ı KALICI olarak 'all'e düşürmesin;
                # her yeni bağlantıda block modu yeniden denenir.
                self.block_failed = False
                url = urls[url_idx % len(urls)]
                self.on_fallback_ws = (url_idx % len(urls)) > 0
                try:
                    async with websockets.connect(url, ping_interval=20, max_size=32_000_000) as ws:
                        logger.info("[LISTENER] WS bağlandı: %s%s (workers=%d)",
                                    url.split("?")[0],
                                    " [YEDEK]" if self.on_fallback_ws else "",
                                    worker_count)
                        backoff = 1.0
                        url_idx = 0  # sonraki reconnect yine birincili dener (kota dönebilir)
                        refresher = asyncio.create_task(self._refresh(ws))
                        try:
                            async for raw in ws:
                                if stop_event is not None and stop_event.is_set():
                                    break
                                await self.process(raw)
                        finally:
                            refresher.cancel()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("WS koptu/reddedildi (%s): %s — %.0fs sonra %s denenecek",
                                   url.split("?")[0], exc, backoff,
                                   "YEDEK WS" if (url_idx + 1) % len(urls) > 0 else "birincil WS")
                    url_idx += 1  # 403/kota vb. → sıradaki adrese dön
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
        finally:
            for w in workers:
                w.cancel()


async def run_helius_listener(stop_event: asyncio.Event | None = None) -> None:
    signer = PumpPortalTrader() if settings.pumpportal_api_key else None
    await HeliusListener(signer=signer).run(stop_event)

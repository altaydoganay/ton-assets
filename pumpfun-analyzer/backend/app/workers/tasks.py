"""Arka plan görevleri.

Görevler kısa ve idempotenttir; gerçek RPC çağrıları adapter registry üzerinden
yapılır. Ağ erişimi yoksa görevler güvenli biçimde no-op döner ve loglar.
"""
from __future__ import annotations

import contextlib
import logging

from .celery_app import celery_app
from ..config import settings
from ..database import SessionLocal
from ..adapters.registry import build_chain_provider
from ..adapters.rpc import RpcUnavailableError
from ..models import Wallet, WalletStatus
from ..services.pipeline import ingest_wallet, analyze_wallet

logger = logging.getLogger(__name__)


def _should_heartbeat(db, category: str, minutes: int = 20) -> bool:
    """Aynı kategoride en son denetim kaydı `minutes` dakikadan eskiyse True.
    Redis'ten bağımsız (DB tabanlı) — böylece nabız Loglar'da her zaman görünür
    ama boğmaz. Hata olursa True döner (görünürlük > sessizlik)."""
    from datetime import datetime, timezone, timedelta
    from ..models import AuditLog
    try:
        last = (db.query(AuditLog).filter(AuditLog.category == category)
                .order_by(AuditLog.id.desc()).first())
        if last is None or last.created_at is None:
            return True
        ts = last.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) > timedelta(minutes=minutes)
    except Exception:  # noqa: BLE001
        return True


@contextlib.contextmanager
def _singleton(name: str, ttl: int = 600):
    """Aynı görevin paralel (worker concurrency) çalışmasını önleyen Redis kilidi.
    Böylece Helius çağrıları katlanmaz. Redis yoksa kilitsiz devam eder."""
    got = True
    r = None
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, socket_connect_timeout=2)
        got = bool(r.set(f"lock:{name}", "1", nx=True, ex=ttl))
    except Exception:  # noqa: BLE001
        got = True  # Redis erişilemezse engelleme
        r = None
    try:
        yield got
    finally:
        if got and r is not None:
            try:
                r.delete(f"lock:{name}")
            except Exception:  # noqa: BLE001
                pass


@celery_app.task(name="app.workers.tasks.ingest_and_analyze_wallet")
def ingest_and_analyze_wallet(address: str) -> dict:
    db = SessionLocal()
    try:
        provider = build_chain_provider()
        try:
            n = ingest_wallet(db, provider, address)
        except RpcUnavailableError as exc:
            logger.warning("RPC erişilemedi, analiz atlandı: %s", exc)
            return {"address": address, "ingested": 0, "error": "rpc_unavailable"}
        res = analyze_wallet(db, address)
        return {"address": address, "ingested": n, "score": res.total, "tracked": res.tracked}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.analyze_discovered")
def analyze_discovered() -> dict:
    """Listener'ın keşfettiği aday cüzdanları parti parti analiz edip puanlar.

    Aday toplama canlı dinleyicide (PumpPortal) yapılır; bu görev `discovered`
    durumundaki cüzdanları Helius ile analiz eder ve uygunları `tracked` yapar.
    """
    from ..services.discovery import analyze_discovered_batch

    db = SessionLocal()
    try:
      with _singleton("analyze_discovered", ttl=600) as got:
        if not got:
            return {"skipped": "locked"}  # zaten çalışıyor (paralel katlanmayı önle)
        try:
            provider = build_chain_provider()
        except Exception as exc:  # noqa: BLE001
            logger.info("Zincir sağlayıcı kurulamadı: %s", exc)
            return {"analyzed": 0, "error": "provider"}
        try:
            results = analyze_discovered_batch(
                db, provider,
                limit=settings.discovery_batch_size,
                ingest_limit=settings.discovery_ingest_limit,
            )
        except RpcUnavailableError as exc:
            logger.warning("Keşif analizi atlandı (RPC): %s", exc)
            return {"analyzed": 0, "error": "rpc_unavailable"}
        tracked = sum(1 for r in results if r.get("tracked"))
        # Tanı: en sık eleme nedenlerini ASCII etiketle logla (Windows findstr uyumlu)
        from collections import Counter
        fc: Counter = Counter()
        for r in results:
            for f in r.get("failures", []):
                fc[f] += 1
        logger.info("[ANALYZE] batch=%d tracked=%d top_fails=%s",
                    len(results), tracked, dict(fc.most_common(5)))
        # Panelde (Loglar) görünür: yeni takibe alım olduysa yaz (nadir/önemli olay);
        # hiç yoksa en sık eleme nedenini ~20 dk'da bir nabız olarak göster.
        try:
            from ..models import AuditLog
            show, msg = False, ""
            if tracked > 0:
                show = True
                msg = f"Analiz: {len(results)} cüzdan incelendi · {tracked} yeni TAKİBE alındı"
            elif _should_heartbeat(db, "analysis", 20):
                show = True
                top = ", ".join(f"{k} ({v})" for k, v in fc.most_common(3)) or "—"
                msg = (f"Analiz: {len(results)} cüzdan incelendi · 0 takibe alındı · "
                       f"en sık eleme: {top}")
            if show:
                db.add(AuditLog(level="info", category="analysis", message=msg,
                                context={"analyzed": len(results), "tracked": tracked,
                                         "top_fails": dict(fc.most_common(5))}))
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return {"analyzed": len(results), "tracked": tracked, "results": results}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reevaluate_analyzed")
def reevaluate_analyzed() -> dict:
    """Analiz edilmiş umut vadeden cüzdanları güncel kriterlerle yeniden
    değerlendir (kayıtlı swap'lardan, Helius'suz). Uygun olanları takibe taşır."""
    from ..services.discovery import reevaluate_analyzed as _re

    db = SessionLocal()
    try:
      with _singleton("reevaluate_analyzed", ttl=600) as got:
        if not got:
            return {"skipped": "locked"}
        result = _re(db)
        logger.info("[REEVAL] reevaluated=%d promoted=%d",
                    result.get("reevaluated", 0), result.get("promoted", 0))
        return result
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.manage_positions")
def manage_positions() -> dict:
    """Açık paper pozisyonlarında TP/SL kontrolü."""
    from ..adapters.registry import build_market_provider
    from ..services.position_manager import manage_positions as _manage

    db = SessionLocal()
    try:
      with _singleton("manage_positions", ttl=120) as got:
        if not got:
            return {"skipped": "locked"}
        closed = _manage(db, build_market_provider())
        return {"closed": len(closed), "details": closed}
    except Exception as exc:  # noqa: BLE001
        logger.warning("TP/SL kontrolü hatası: %s", exc)
        return {"closed": 0, "error": str(exc)[:120]}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.poll_tracked_wallets")
def poll_tracked_wallets() -> dict:
    """Takip edilen cüzdanların TAZE alımlarını güvenilir biçimde yakalar (poll).

    Canlı WS dinleyicisi olayları kaçırabildiğinden, bu görev her döngüde takip
    edilen cüzdanların son işlemlerini Enhanced ile çeker ve taze alımları işleme
    hattına yönlendirir. Redis ile imza-bazlı dedup (çift işlem yok)."""
    from ..adapters.registry import build_market_provider
    from ..services.wallet_watch import poll_tracked_wallets as _poll

    db = SessionLocal()
    try:
      with _singleton("poll_tracked_wallets", ttl=120) as got:
        if not got:
            return {"skipped": "locked"}
        # Redis TTL ile imza dedup (kaçıran/çift işlemeyi önler)
        r = None
        try:
            import redis as _redis
            r = _redis.from_url(settings.redis_url, socket_connect_timeout=2)
        except Exception:  # noqa: BLE001
            r = None
        fresh = int(settings.tracked_poll_fresh_seconds)

        def _should(sig: str) -> bool:
            if r is None:
                return True
            try:
                return bool(r.set(f"watch:{sig}", "1", nx=True, ex=fresh + 120))
            except Exception:  # noqa: BLE001
                return True

        try:
            chain = build_chain_provider(throttle=False)
        except Exception as exc:  # noqa: BLE001
            logger.info("Zincir sağlayıcı kurulamadı (watch): %s", exc)
            return {"triggered": 0, "error": "provider"}
        signer = None
        try:
            if settings.pumpportal_api_key:
                from ..adapters.pumpportal import PumpPortalTrader
                signer = PumpPortalTrader()
        except Exception:  # noqa: BLE001
            signer = None
        result = _poll(
            db, chain, market=build_market_provider(), signer=signer,
            per_wallet=int(settings.tracked_poll_per_wallet),
            fresh_seconds=fresh, should_process=_should,
        )
        # Panelde (Loglar) GÖRÜNÜR durum: aktivite varsa hemen yaz; aktivite yoksa
        # en çok ~20 dk'da bir "nabız" yaz (Loglar'ı boğmadan izleyici canlı mı,
        # cüzdanlar alım yapıyor mu görebilesin). Not: [WATCH] logger satırları
        # yalnızca `docker logs`'ta olur; panel sadece bu DB kaydını gösterir.
        try:
            polled = result.get("polled", 0)
            fresh_buys = result.get("fresh_buys", 0)
            triggered = result.get("triggered", 0)
            show = (fresh_buys > 0) or (triggered > 0) or _should_heartbeat(db, "watch", 20)
            if show:
                from ..models import AuditLog
                from ..services.settings_service import get_setting
                gate = get_setting(db, "risk").get("token_gate", "safety")
                reasons = result.get("reasons") or {}
                reason_txt = " · ".join(f"{k} ({v})" for k, v in reasons.items())
                if not polled:
                    msg = "İzleme: takip edilen aktif cüzdan yok (havuz boş)"
                elif fresh_buys == 0:
                    msg = (f"İzleme: {polled} takip cüzdanı yoklandı · taze alım YOK "
                           f"(cüzdanlar şu an alım yapmıyor)")
                elif triggered == 0:
                    # GERÇEK sebebi göster (veto / hata / puan) — kör tahmin yok.
                    msg = (f"İzleme: {polled} cüzdan · {fresh_buys} taze alım · 0 işlem · "
                           f"kapı={gate} · sebep: {reason_txt or 'bu döngüde yeni alım işlenmedi (dedup)'}")
                else:
                    msg = (f"İzleme: {polled} cüzdan · {fresh_buys} taze alım · "
                           f"{triggered} işlem tetiklendi · kapı={gate}")
                db.add(AuditLog(level="info", category="watch", message=msg, context=result))
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return result
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reanalyze_tracked")
def reanalyze_tracked() -> dict:
    db = SessionLocal()
    try:
        tracked = db.query(Wallet).filter(Wallet.status == WalletStatus.tracked.value).all()
        for w in tracked:
            ingest_and_analyze_wallet.delay(w.address)
        return {"queued": len(tracked)}
    finally:
        db.close()

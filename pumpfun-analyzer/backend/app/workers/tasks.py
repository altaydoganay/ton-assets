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
        fresh = int(settings.tracked_poll_fresh_seconds)
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
            fresh_seconds=fresh,
            max_wallets=int(settings.tracked_poll_max_wallets),
        )
        # Panelde (Loglar) GÖRÜNÜR durum: aktivite varsa hemen yaz; aktivite yoksa
        # en çok ~20 dk'da bir "nabız" yaz (Loglar'ı boğmadan izleyici canlı mı,
        # cüzdanlar alım yapıyor mu görebilesin). Not: [WATCH] logger satırları
        # yalnızca `docker logs`'ta olur; panel sadece bu DB kaydını gösterir.
        try:
            polled = result.get("polled", 0)
            fresh_buys = result.get("fresh_buys", 0)
            triggered = result.get("triggered", 0)
            mirrored = result.get("mirrored_sells", 0)
            show = (fresh_buys > 0) or (triggered > 0) or (mirrored > 0) or _should_heartbeat(db, "watch", 20)
            if show:
                from datetime import datetime, timezone, timedelta
                from ..models import AuditLog, PaperTrade
                from ..services.settings_service import get_setting
                gate = get_setting(db, "risk").get("token_gate", "safety")
                reasons = result.get("reasons") or {}
                reason_txt = " · ".join(f"{k} ({v})" for k, v in reasons.items())
                # Dedup'tan BAĞIMSIZ gerçek durum: son 1 saatte kaç paper alım açıldı
                # ve en son işlem KARARI neydi (alım başına detay).
                hr_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                paper_1h = (db.query(PaperTrade)
                            .filter(PaperTrade.side == "buy", PaperTrade.created_at >= hr_ago).count())
                last_dec = (db.query(AuditLog).filter(AuditLog.category == "trading")
                            .order_by(AuditLog.id.desc()).first())
                last_txt = (last_dec.message[:130] if last_dec else "henüz alım-başına karar yok")
                tail = f" · son 1s paper alım: {paper_1h} · son karar: {last_txt}"
                if not polled:
                    msg = "İzleme: takip edilen aktif cüzdan yok (havuz boş)"
                elif fresh_buys == 0:
                    msg = (f"İzleme: {polled} takip cüzdanı yoklandı · taze alım YOK "
                           f"(cüzdanlar şu an alım yapmıyor)") + tail
                elif triggered == 0:
                    msg = (f"İzleme: {polled} cüzdan · {fresh_buys} taze alım · 0 işlem · "
                           f"kapı={gate} · sebep: {reason_txt or 'bu döngüde yeni alım yok (dedup)'}") + tail
                else:
                    msg = (f"İzleme: {polled} cüzdan · {fresh_buys} taze · "
                           f"{triggered} ALIM açıldı · {mirrored} SATIŞ yansıtıldı · kapı={gate}") + tail
                db.add(AuditLog(level="info", category="watch", message=msg, context=result))
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return result
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.prune_underperformers")
def prune_underperformers() -> dict:
    """Kopya performansı kötü (ardışık zarar / kümülatif drawdown) cüzdanları
    otomatik engeller — paper aşamasında başarısızları eler."""
    from ..services.copy_performance import prune_underperformers as _prune
    from ..services.settings_service import get_setting

    db = SessionLocal()
    try:
      with _singleton("prune_underperformers", ttl=300) as got:
        if not got:
            return {"skipped": "locked"}
        r = get_setting(db, "risk")
        return _prune(
            db,
            enabled=bool(r.get("copy_prune_enabled", True)),
            max_consecutive_losses=int(r.get("copy_max_consecutive_losses", 5)),
            min_closed_trades=int(r.get("copy_min_closed_trades", 6)),
            min_pnl_sol=float(r.get("copy_min_pnl_sol", 0.0)),
        )
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


@celery_app.task(name="app.workers.tasks.drain_backlog")
def drain_backlog(target: int = 2000, ingest_limit: int = 80, budget_seconds: int = 180,
                  done: int = 0, tracked: int = 0, started_at: str | None = None) -> dict:
    """Keşif BACKLOG'unu toplu işler: `discovered` (yalnızca adres) cüzdanların
    işlem geçmişini ZİNCİRDEN çeker (Helius kredisi) ve puanlar.

    KENDİNİ ZİNCİRLER: bir görev çalışması yalnızca `budget_seconds` (vars. 180 sn)
    kadar çalışır — worker'ı uzun süre kilitlememek için. Hedefe (`target`) ya da
    backlog'a ulaşılana dek, kümülatif sayaçları (done/tracked) bir sonraki çalışmaya
    geçirerek kendini YENİDEN KUYRUĞA ALIR. Böylece "2000 iste, 225'te durdu"
    (tek görevin süre bütçesi) sorunu kalkar; ilerleme _meta_backlog_drain'de
    kümülatif görünür. Her cüzdan ~1 Enhanced isteği ≈ ~10 kredi."""
    import time as _t
    from datetime import datetime, timezone
    from ..models import AuditLog
    from ..services.discovery import analyze_discovered_batch, count_pending
    from ..services.settings_service import set_setting

    first_run = done == 0 and started_at is None
    started_at = started_at or datetime.now(timezone.utc).isoformat()

    def _progress(db, *, running, reason=None):
        set_setting(db, "_meta_backlog_drain", {
            "running": running, "processed": done, "tracked": tracked, "target": target,
            "remaining": count_pending(db), "started_at": started_at,
            "ts": datetime.now(timezone.utc).isoformat(), "reason": reason})

    def _audit(db, msg):
        try:
            db.add(AuditLog(level="info", category="discovery", message=msg)); db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()

    db = SessionLocal()
    try:
      with _singleton("drain_backlog", ttl=budget_seconds + 60) as got:
        if not got:
            return {"skipped": "zaten çalışıyor"}
        if first_run:
            # Worker'ın görevi GERÇEKTEN aldığının kanıtı (Loglar panelinde görünür).
            _audit(db, f"🔍 Backlog analizi BAŞLADI — hedef {target} cüzdan (~{target*10} kredi)")
        _progress(db, running=True)
        try:
            chain = build_chain_provider(throttle=True)  # keşif: RPS/kredi koruması açık
        except Exception as exc:  # noqa: BLE001
            logger.info("Zincir sağlayıcı kurulamadı (drain): %s", exc)
            _progress(db, running=False, reason="zincir sağlayıcı kurulamadı (HELIUS_API_KEY/RPC?)")
            _audit(db, "Backlog analizi DURDU — zincir sağlayıcı kurulamadı")
            return {"error": "provider"}
        start = _t.monotonic()
        stalled = False
        while done < target and (_t.monotonic() - start) < budget_seconds:
            chunk = min(25, target - done)
            res = analyze_discovered_batch(db, chain, limit=chunk, ingest_limit=ingest_limit)
            if not res:
                stalled = True
                break  # backlog bitti ya da RPC down (analyze_discovered_batch break eder)
            done += len(res)
            tracked += sum(1 for r in res if r.get("tracked"))
            _progress(db, running=True)
        remaining = count_pending(db)
        # Hedefe ulaşılmadı, backlog hâlâ var ve RPC sorunu yoksa: KENDİNİ yeniden
        # kuyruğa al (kısa hop'lar hâlinde devam). Aksi halde BİTTİ olarak işaretle.
        if done < target and remaining > 0 and not stalled:
            _progress(db, running=True)
            drain_backlog.apply_async(
                kwargs={"target": target, "ingest_limit": ingest_limit,
                        "budget_seconds": budget_seconds, "done": done,
                        "tracked": tracked, "started_at": started_at},
                countdown=2)  # 2 sn: singleton kilidinin serbest kalmasına izin ver
            logger.info("[DRAIN] hop done=%d/%d tracked=%d remaining=%d -> devam", done, target, tracked, remaining)
            return {"processed": done, "tracked": tracked, "remaining": remaining, "continuing": True}
        reason = None
        if done == 0 and stalled:
            reason = ("hiç işlenmedi — RPC/Helius erişilemiyor olabilir veya backlog boş"
                      if remaining else "backlog boş")
        elif stalled and remaining == 0:
            reason = "backlog bitti"
        _progress(db, running=False, reason=reason)
        _audit(db, f"✅ Backlog analizi BİTTİ — {done} işlendi · +{tracked} takibe · {remaining} kaldı"
               + (f" ({reason})" if reason else ""))
        logger.info("[DRAIN] BİTTİ done=%d tracked=%d remaining=%d", done, tracked, remaining)
        return {"processed": done, "tracked": tracked, "remaining": remaining, "reason": reason}
    finally:
        db.close()

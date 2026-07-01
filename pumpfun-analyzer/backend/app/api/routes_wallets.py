from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Swap, Wallet, WalletScore, WalletStatus, WalletRelationship
from ..schemas import WalletDetail, WalletOut, WalletScoreOut
from ..adapters.registry import build_chain_provider
from ..adapters.rpc import RpcUnavailableError
from ..services.analysis_service import get_or_create_wallet
from ..services.pipeline import ingest_wallet, analyze_wallet
from ..services.settings_service import get_setting, set_setting, get_strategy_mode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wallets", tags=["wallets"])


def _require_copy_mode(db: Session) -> None:
    if get_strategy_mode(db) != "copy":
        raise HTTPException(409, "AI Trade aktif: cüzdan/copy işlemleri durduruldu. Cüzdan tarama veya rebuild için önce Copy Trade moduna geç.")


class WalletCreate(BaseModel):
    address: str
    label: str | None = None
    limit: int = 100  # taranacak son işlem sayısı


QUALITY_REBUILD_KEY = "_meta_quality_rebuild"


def _ingest_and_score(db: Session, address: str, limit: int):
    """Cüzdanın işlemlerini çekip puanlar. RPC yoksa açıklayıcı hata döner."""
    provider = build_chain_provider()
    try:
        ingest_wallet(db, provider, address, limit=limit)
    except RpcUnavailableError as exc:
        raise HTTPException(503, f"Zincir sağlayıcıya ulaşılamadı (RPC/Helius): {exc}")
    return analyze_wallet(db, address)


@router.post("/cull")
def cull_wallets_endpoint(preset: str = Query("balanced"), dry_run: bool = Query(True),
                          db: Session = Depends(get_db)):
    """Takip cüzdanlarını kaliteye göre ELE (aktiflik + kârlılık + örneklem + skor).

    preset: elite | strict | balanced | light. dry_run=true => yalnızca ÖNİZLEME (kaç kalır/
    elenir), yazmaz. dry_run=false => uygular (düşenler below_threshold'a) ve barı
    (thresholds.wallet) preset skoruna yükseltir ki eleme KALICI olsun."""
    _require_copy_mode(db)
    from ..services.culling import cull_wallets, CULL_PRESETS
    if preset not in CULL_PRESETS:
        raise HTTPException(400, f"Bilinmeyen preset: {preset}")
    res = cull_wallets(db, preset, dry_run=dry_run)
    if not dry_run:
        logger.info("[CULL] preset=%s kept=%s dropped=%s", preset, res["kept"], res["dropped"])
    return res


def _rebuild_status_payload(db: Session, meta: dict | None = None) -> dict:
    meta = dict(meta or get_setting(db, QUALITY_REBUILD_KEY) or {})
    ids = meta.pop("candidate_ids", None) or []
    total = int(meta.get("total") or len(ids) or 0)
    processed = int(meta.get("processed") or 0)
    meta["total"] = total
    meta["processed"] = processed
    meta["remaining"] = max(0, total - processed)
    meta["percent"] = round((processed / total) * 100, 1) if total else 0.0
    meta["tracked_now"] = (
        db.query(func.count(Wallet.id))
        .filter(Wallet.status == WalletStatus.tracked.value)
        .scalar()
        or 0
    )
    last_ts = None
    if isinstance(meta.get("last_step"), dict):
        last_ts = meta["last_step"].get("ts")
    meta["last_progress_at"] = last_ts or meta.get("started_at")
    try:
        if meta.get("status") == "running" and meta.get("last_progress_at"):
            dt = datetime.fromisoformat(str(meta["last_progress_at"]).replace("Z", "+00:00"))
            meta["stalled_seconds"] = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        else:
            meta["stalled_seconds"] = 0
    except Exception:
        meta["stalled_seconds"] = None
    return meta


@router.get("/quality-rebuild/status")
def quality_rebuild_status(db: Session = Depends(get_db)):
    return _rebuild_status_payload(db)


@router.post("/quality-rebuild/cancel")
def cancel_quality_rebuild(db: Session = Depends(get_db)):
    meta = dict(get_setting(db, QUALITY_REBUILD_KEY) or {})
    meta["status"] = "cancelled"
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    meta["candidate_ids"] = []
    set_setting(db, QUALITY_REBUILD_KEY, meta)
    return _rebuild_status_payload(db, meta)


@router.post("/quality-rebuild/start")
def start_quality_rebuild(
    preset: str = Query("elite"),
    db: Session = Depends(get_db),
):
    """Kalite rebuild işini başlatır; gerçek işlem /step ile parça parça ilerler."""
    _require_copy_mode(db)
    from ..services.culling import CULL_PRESETS, apply_elite_wallet_policy

    if preset not in CULL_PRESETS:
        raise HTTPException(400, f"Bilinmeyen preset: {preset}")
    if preset == "elite":
        apply_elite_wallet_policy(db)

    thresholds = get_setting(db, "thresholds")
    thresholds["max_tracked"] = 0
    set_setting(db, "thresholds", thresholds)

    status_counts_before = dict(
        db.query(Wallet.status, func.count(Wallet.id)).group_by(Wallet.status).all()
    )
    tracked_reset = (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .update({Wallet.status: WalletStatus.below_threshold.value}, synchronize_session=False)
    )
    db.commit()

    candidate_ids = [
        wid
        for (wid,) in (
            db.query(Wallet.id)
            .join(Swap, Swap.wallet_address == Wallet.address)
            .filter(Wallet.status != WalletStatus.blocked.value)
            .group_by(Wallet.id)
            .order_by(Wallet.latest_score.desc().nullslast(), Wallet.id.asc())
            .all()
        )
    ]
    meta = {
        "status": "running",
        "preset": preset,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "candidate_ids": candidate_ids,
        "total": len(candidate_ids),
        "processed": 0,
        "tracked_reset": int(tracked_reset or 0),
        "status_counts_before": status_counts_before,
        "last_step": None,
        "cull": None,
    }
    set_setting(db, QUALITY_REBUILD_KEY, meta)
    logger.info("[QUALITY_REBUILD] started preset=%s reset=%s total=%s", preset, tracked_reset, len(candidate_ids))
    return _rebuild_status_payload(db, meta)


@router.post("/quality-rebuild/step")
def step_quality_rebuild(
    batch_size: int = Query(200, ge=1, le=1000),
    budget_seconds: float = Query(10.0, ge=1.0, le=60.0),
    scan_transfers: bool = Query(False),
    transfer_scan_limit: int = Query(50, ge=20, le=250),
    db: Session = Depends(get_db),
):
    """Kalite rebuild'in bir parçasını çalıştırır ve progress döner.

    Varsayılan hızlı modda yalnızca DB'deki kayıtlı swap/metriklerle yeniden puanlar.
    scan_transfers=true özel tanı/derin tarama içindir; her cüzdan için zincir geçmişi
    çektiğinden çok yavaştır ve UI akışını kilitleyebilir. Cüzdanlar arası bağ
    kayıtları normal ingestion/backlog sırasında da dolar.
    """
    _require_copy_mode(db)
    from ..services.culling import cull_wallets

    meta = dict(get_setting(db, QUALITY_REBUILD_KEY) or {})
    if meta.get("status") != "running":
        return _rebuild_status_payload(db, meta)

    ids = list(meta.get("candidate_ids") or [])
    processed = int(meta.get("processed") or 0)
    total = len(ids)
    start = time.monotonic()
    scanned = 0
    to_tracked = 0
    to_below = 0
    to_rejected = 0
    transfer_scanned = 0
    transfer_scan_failed = 0
    provider = None
    if scan_transfers:
        try:
            provider = build_chain_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QUALITY_REBUILD] transfer scan provider unavailable: %s", exc)

    while processed < total and scanned < batch_size and (time.monotonic() - start) < budget_seconds:
        wallet_id = ids[processed]
        processed += 1
        wallet = db.get(Wallet, wallet_id)
        if wallet is None:
            continue
        before = wallet.status
        try:
            if provider is not None:
                try:
                    ingest_wallet(db, provider, wallet.address, limit=transfer_scan_limit)
                    transfer_scanned += 1
                except Exception as exc:  # noqa: BLE001
                    transfer_scan_failed += 1
                    logger.warning("[QUALITY_REBUILD] transfer scan failed %s: %s", wallet.address, exc)
            analyze_wallet(db, wallet.address)
            db.refresh(wallet)
            scanned += 1
            if before != wallet.status:
                if wallet.status == WalletStatus.tracked.value:
                    to_tracked += 1
                elif wallet.status == WalletStatus.below_threshold.value:
                    to_below += 1
                elif wallet.status == WalletStatus.rejected.value:
                    to_rejected += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QUALITY_REBUILD] wallet failed %s: %s", wallet.address, exc)
            scanned += 1

    meta["processed"] = processed
    meta["last_step"] = {
        "scanned": scanned,
        "to_tracked": to_tracked,
        "to_below": to_below,
        "to_rejected": to_rejected,
        "transfer_scanned": transfer_scanned,
        "transfer_scan_failed": transfer_scan_failed,
        "transfer_scan_mode": "deep" if provider is not None else "fast",
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if processed >= total:
        cull_result = cull_wallets(db, str(meta.get("preset") or "elite"), dry_run=False)
        meta["status"] = "done"
        meta["finished_at"] = datetime.now(timezone.utc).isoformat()
        meta["cull"] = cull_result
        meta["candidate_ids"] = []
        logger.info("[QUALITY_REBUILD] done scanned=%s kept=%s dropped=%s", total, cull_result["kept"], cull_result["dropped"])

    set_setting(db, QUALITY_REBUILD_KEY, meta)
    return _rebuild_status_payload(db, meta)


@router.post("/quality-rebuild")
def rebuild_wallet_quality(
    preset: str = Query("elite"),
    passes: int = Query(6, ge=1, le=20),
    budget_seconds: float = Query(45.0, ge=5.0, le=180.0),
    max_wallets: int = Query(10000, ge=100, le=50000),
    db: Session = Depends(get_db),
):
    """Takip listesini sıfırla, kayıtlı cüzdanları yeni kalite politikasıyla yeniden puanla.

    Zincire gitmez; yalnızca DB'deki swap/veri ile çalışır. Amaç canlı/paper motorun
    eski geniş takip listesini kullanmasını durdurup 10sn copyability odaklı daha
    küçük bir takip seti üretmektir.
    """
    _require_copy_mode(db)
    from ..services.culling import CULL_PRESETS, apply_elite_wallet_policy, cull_wallets
    from ..services.pipeline import rescore_wallets_from_storage
    from ..services.settings_service import get_setting, set_setting, get_strategy_mode

    if preset not in CULL_PRESETS:
        raise HTTPException(400, f"Bilinmeyen preset: {preset}")

    policy = apply_elite_wallet_policy(db) if preset == "elite" else None
    # Rebuild sırasında üst sınırı geçici kaldır: aksi halde ilk puanlanan 50 cüzdan
    # listeyi doldurur, daha iyi copyability'ye sahip sonraki adaylar takibe giremez.
    thresholds = get_setting(db, "thresholds")
    thresholds["max_tracked"] = 0
    set_setting(db, "thresholds", thresholds)

    status_counts_before = dict(
        db.query(Wallet.status, func.count(Wallet.id)).group_by(Wallet.status).all()
    )
    tracked_reset = (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .update({Wallet.status: WalletStatus.below_threshold.value}, synchronize_session=False)
    )
    db.commit()

    totals = {
        "scanned": 0, "skipped_no_data": 0, "to_tracked": 0,
        "to_below": 0, "to_rejected": 0, "remaining": 0,
    }
    pass_results = []
    for _ in range(passes):
        r = rescore_wallets_from_storage(
            db,
            budget_seconds=budget_seconds,
            max_wallets=max_wallets,
        )
        pass_results.append(r)
        for key in ("scanned", "skipped_no_data", "to_tracked", "to_below", "to_rejected"):
            totals[key] += int(r.get(key) or 0)
        totals["remaining"] = int(r.get("remaining") or 0)
        if totals["remaining"] <= 0:
            break

    cull_result = cull_wallets(db, preset, dry_run=False)
    status_counts_after = dict(
        db.query(Wallet.status, func.count(Wallet.id)).group_by(Wallet.status).all()
    )
    logger.info(
        "[QUALITY_REBUILD] preset=%s reset=%s scanned=%s tracked=%s dropped=%s",
        preset, tracked_reset, totals["scanned"], cull_result["kept"], cull_result["dropped"],
    )
    return {
        "preset": preset,
        "tracked_reset": tracked_reset,
        "status_counts_before": status_counts_before,
        "status_counts_after": status_counts_after,
        "policy_applied": bool(policy),
        "totals": totals,
        "passes": pass_results,
        "cull": cull_result,
    }


@router.post("/rescan")
def rescan_wallets(db: Session = Depends(get_db)):
    """Mevcut cüzdanları DEPOLANMIŞ swap'larla yeniden puanlar (kredi harcamaz).

    Kriter/eşik değişikliğinden (örn. takip eşiği 55 + gevşeyen uygunluk) sonra
    eski 'rejected/below_threshold/analyzed' kararlarını günceller; artık eşiği
    geçen cüzdanlar TAKİBE alınır. Zincire gitmez. Büyük havuzlarda zaman
    bütçesi (20sn) aşılırsa kalan `remaining` ile döner — tekrar çağrılabilir."""
    _require_copy_mode(db)
    from ..services.pipeline import rescore_wallets_from_storage
    return rescore_wallets_from_storage(db)


@router.get("", response_model=list[WalletOut])
def list_wallets(
    status: str | None = Query(None),
    min_score: float | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Wallet)
    if status:
        q = q.filter(Wallet.status == status)
    if min_score is not None:
        q = q.filter(Wallet.latest_score >= min_score)
    q = q.order_by(Wallet.latest_score.desc().nullslast()).offset(offset).limit(limit)
    return q.all()


@router.post("", response_model=WalletDetail, status_code=201)
def add_wallet(body: WalletCreate, db: Session = Depends(get_db)):
    """Cüzdan ekle, son işlemlerini çekip analiz et ve puanla.

    Not: İşlem çekimi RPC/Helius'a bağlıdır; çok sayıda işlemde birkaç dakika
    sürebilir. `limit` ile taranacak işlem sayısı sınırlanır.
    """
    _require_copy_mode(db)
    w = get_or_create_wallet(db, body.address, source="manual")
    if body.label:
        w.label = body.label
        db.commit()
    _ingest_and_score(db, body.address, body.limit)
    db.refresh(w)
    return w


@router.post("/{address}/reanalyze", response_model=WalletDetail)
def reanalyze_wallet(address: str, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    _require_copy_mode(db)
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    _ingest_and_score(db, address, limit)
    db.refresh(w)
    return w


@router.get("/tracked", response_model=list[WalletOut])
def tracked_wallets(db: Session = Depends(get_db)):
    return (
        db.query(Wallet)
        .filter(Wallet.status == WalletStatus.tracked.value)
        .order_by(Wallet.latest_score.desc())
        .all()
    )


@router.get("/leaderboard")
def leaderboard(limit: int = Query(300, le=1000), db: Session = Depends(get_db)):
    """TÜM puanlanmış cüzdanları lider performansı + 0.01 SOL gecikmeli copy
    simülasyonuyla döner. Varsayılan sıralama copyability odaklıdır."""
    rows = (db.query(Wallet)
            .filter(Wallet.latest_score.isnot(None))
            .all())
    rows.sort(
        key=lambda w: (
            (w.metrics or {}).get("copyability_score") or 0,
            (w.metrics or {}).get("copy_pnl_10s_sol") or 0,
            w.latest_score or 0,
        ),
        reverse=True,
    )
    out = []
    for w in rows[:limit]:
        m = w.metrics or {}
        out.append({
            "address": w.address, "label": w.label, "status": w.status,
            "score": w.latest_score, "confidence": w.confidence,
            "win_rate": m.get("win_rate"),
            "realized_pnl_sol": m.get("realized_pnl_sol"),
            "profit_factor": m.get("profit_factor"),
            "closed_positions": m.get("closed_positions"),
            "token_diversity": m.get("token_diversity"),
            "median_hold_seconds": m.get("median_hold_seconds"),
            "history_days": m.get("history_days"),
            "avg_buy_size_sol": m.get("avg_buy_size_sol"),
            "copyability_score": m.get("copyability_score"),
            "copy_pnl_10s_sol": m.get("copy_pnl_10s_sol"),
            "copy_pnl_30s_sol": m.get("copy_pnl_30s_sol"),
            "avg_entry_jump_10s": m.get("avg_entry_jump_10s"),
            "copy_profit_factor_10s": m.get("copy_profit_factor_10s"),
            "copy_coverage_ratio": m.get("copy_coverage_ratio"),
            "copy_sample_size": m.get("copy_sample_size"),
            "related_known_wallet_count": m.get("related_known_wallet_count"),
            "related_tracked_wallet_count": m.get("related_tracked_wallet_count"),
            "last_analyzed": w.last_analyzed.isoformat() if w.last_analyzed else None,
        })
    return out


@router.get("/{address}", response_model=WalletDetail)
def get_wallet(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    return w


@router.get("/{address}/score-history", response_model=list[WalletScoreOut])
def score_history(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    return (
        db.query(WalletScore)
        .filter(WalletScore.wallet_id == w.id)
        .order_by(WalletScore.created_at.asc())
        .all()
    )


@router.get("/{address}/relationships")
def relationships(address: str, db: Session = Depends(get_db)):
    rels = (
        db.query(WalletRelationship)
        .filter(
            (WalletRelationship.source_address == address)
            | (WalletRelationship.target_address == address)
        )
        .all()
    )
    return [
        {
            "source": r.source_address,
            "target": r.target_address,
            "kind": r.kind,
            "confidence": r.confidence,
            "evidence": r.evidence,
        }
        for r in rels
    ]


@router.post("/{address}/block", response_model=WalletOut)
def block_wallet(address: str, db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    w.status = WalletStatus.blocked.value
    db.commit()
    db.refresh(w)
    return w


@router.post("/{address}/approve", response_model=WalletOut)
def approve_wallet(address: str, db: Session = Depends(get_db)):
    _require_copy_mode(db)
    w = db.query(Wallet).filter(Wallet.address == address).first()
    if not w:
        raise HTTPException(404, "Cüzdan bulunamadı")
    w.status = WalletStatus.tracked.value
    db.commit()
    db.refresh(w)
    return w


@router.post("/{address}/copy-amount")
def set_copy_amount(address: str, sol: float = Query(...), db: Session = Depends(get_db)):
    """Bu cüzdana özel kopya SOL miktarı ata. sol<=0 => override'ı kaldır (varsayılana
    döner: paper'da sabit miktar, canlıda fixed/orantılı)."""
    _require_copy_mode(db)
    from ..services.settings_service import get_setting, set_setting, get_strategy_mode
    overrides = dict(get_setting(db, "copy_overrides") or {})
    if sol and sol > 0:
        overrides[address] = float(sol)
    else:
        overrides.pop(address, None)
    set_setting(db, "copy_overrides", overrides)
    return {"address": address, "copy_override_sol": overrides.get(address)}

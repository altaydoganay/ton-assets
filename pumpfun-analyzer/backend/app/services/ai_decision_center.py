"""AI Trade karar merkezi.

Bu servis teknik audit loglarını ve paper trade kayıtlarını kullanıcıya okunur bir
"neden aldı / neden almadı / nerede çıktı" ekranına dönüştürür. Şema değişikliği
yapmaz; mevcut PaperTrade ve AuditLog kayıtlarından türetir.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, PaperTrade, Token
from .settings_service import get_setting


def _short(a: str | None) -> str:
    if not a:
        return "—"
    return f"{a[:4]}…{a[-4:]}" if len(a) > 10 else a


def _is_ai_context(ctx: dict[str, Any], msg: str = "") -> bool:
    return (
        str(ctx.get("strategy") or "") == "ai"
        or ctx.get("wallet") == "AI_TRADE"
        or "AI" in (msg or "")
    )


def _is_ai_trade(t: PaperTrade) -> bool:
    return t.wallet_address == "AI_TRADE" or str(t.reason or "").startswith("ai-")


def _reason_text(raw: Any, fallback: str = "Bilinmeyen") -> str:
    if raw is None:
        return fallback
    if isinstance(raw, list):
        raw = raw[0] if raw else fallback
    if isinstance(raw, dict):
        raw = raw.get("reason") or raw.get("message") or fallback
    text = str(raw or fallback).strip()
    return text[:180] if text else fallback


def _norm_text(text: str | None) -> str:
    """Türkçe karakterleri ASCII'ye normalize ederek karar loglarını sağlam sınıflandırır.

    Python lower() Türkçe I/İ konusunda locale kullanmadığı için "AÇILDI" /
    "ALMADI" gibi loglar bazen action olarak yakalanmıyordu. Bu da AI
    ekranında "14 alım var ama Aldı 0" gibi tutarsızlıklara yol açıyordu.
    """
    table = str.maketrans({
        "İ": "i", "I": "i", "ı": "i",
        "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
        "Ü": "u", "ü": "u", "Ö": "o", "ö": "o",
        "Ç": "c", "ç": "c",
    })
    return str(text or "").translate(table).lower()




def _baseline_since(db: Session) -> datetime | None:
    raw = get_setting(db, "stats_baseline") or {}
    value = raw.get("ai") or raw.get("all")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None

def _bucket_reason(reason: str) -> str:
    low = _norm_text(reason)
    if "fiyat" in low or "price" in low:
        return "Güvenilir fiyat yok"
    if "veto" in low or "honeypot" in low or "satılabilir" in low or "rug" in low:
        return "Güvenlik / satılabilirlik riski"
    if "puan" in low or "score" in low or "skor" in low:
        return "Token puanı düşük"
    if "likidite" in low or "liquidity" in low:
        return "Likidite zayıf"
    if "yaş" in low or "eski" in low or "yeni" in low:
        return "Zamanlama / token yaşı"
    if "limit" in low or "harcama" in low or "zarar" in low:
        return "Risk limiti"
    if "kilit" in low or "ai live" in low or "canlı" in low:
        return "Canlı güvenlik kilidi"
    if "motor" in low or "kapalı" in low:
        return "Motor kapalı"
    if "token başına" in low or "açık pozisyon" in low:
        return "Aynı token pozisyon limiti"
    return reason[:80] if len(reason) > 80 else reason


def _decision_action(msg: str, ctx: dict[str, Any]) -> str:
    low = _norm_text(msg)

    # Açılış logları hem audit context'inden hem de metinden anlaşılabilir.
    # Türkçe karakter normalize edildiği için "İşlem AÇILDI" güvenilir yakalanır.
    if ctx.get("opened_reason") or "islem acildi" in low or "islem açildi" in low:
        return "opened"

    if ctx.get("exit_reason") or any(x in low for x in ("kapat", "cikis", "çikis", "stop", "take-profit", "trailing", "max hold", "zaman cikisi")):
        return "exit"

    if ctx.get("blocked") or ctx.get("trade_blocked"):
        return "blocked"

    if any(x in low for x in ("almadi", "engellendi", "blok", "islem yok", "reddedildi", "skip", "skipped")):
        return "blocked"

    return "info"


def _exit_reason(reason: str | None) -> str:
    low = str(reason or "").lower()
    if "stop-loss" in low or low == "sl":
        return "Stop-loss"
    if "take-profit" in low or low == "tp":
        return "Take-profit"
    if "trailing" in low or "takip eden" in low:
        return "Trailing stop"
    if "zaman" in low or "time" in low:
        return "Zaman çıkışı"
    if "mirror" in low or "lider" in low:
        return "Lider satışı"
    if "ghost" in low:
        return "Ghost/stale temizlik"
    return "Diğer / bilinmiyor"


def _token_meta(db: Session, mint: str) -> dict[str, Any]:
    t = db.query(Token).filter(Token.mint == mint).first()
    if not t:
        return {"mint": mint, "name": None, "symbol": None, "score": None}
    return {
        "mint": mint,
        "name": t.name,
        "symbol": t.symbol,
        "score": t.latest_score,
        "metrics": t.metrics or {},
        "risk_flags": t.risk_flags or [],
    }


def _audit_by_signature(db: Session, signatures: set[str]) -> dict[str, AuditLog]:
    if not signatures:
        return {}
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.category == "trading")
        .order_by(AuditLog.id.desc())
        .limit(8000)
        .all()
    )
    out: dict[str, AuditLog] = {}
    for r in rows:
        sig = (r.context or {}).get("signature")
        if sig in signatures and sig not in out:
            out[str(sig)] = r
    return out


def _build_sessions(db: Session, limit: int = 50, since: datetime | None = None) -> list[dict[str, Any]]:
    q = db.query(PaperTrade).filter(PaperTrade.wallet_address == "AI_TRADE")
    if since is not None:
        q = q.filter(PaperTrade.created_at >= since)
    rows = q.order_by(PaperTrade.created_at.asc(), PaperTrade.id.asc()).all()
    sigs = {r.source_signature for r in rows if r.source_signature}
    audits = _audit_by_signature(db, set(str(s) for s in sigs))
    sessions: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}

    for t in rows:
        if not _is_ai_trade(t):
            continue
        if t.side == "buy":
            sess = active.get(t.token_mint)
            if not sess:
                audit = audits.get(str(t.source_signature or ""))
                ctx = audit.context if audit else {}
                why = _reason_text(ctx.get("reason") or ctx.get("opened_reason"), t.reason or "AI uygun gördü")
                sess = {
                    "token_mint": t.token_mint,
                    "token": _token_meta(db, t.token_mint),
                    "status": "open",
                    "entry_time": t.created_at,
                    "exit_time": None,
                    "entry_price_sol": t.price_sol,
                    "exit_price_sol": None,
                    "cost_sol": 0.0,
                    "proceeds_sol": 0.0,
                    "qty": 0.0,
                    "pnl_sol": 0.0,
                    "pnl_pct": None,
                    "hold_minutes": None,
                    "buy_count": 0,
                    "sell_count": 0,
                    "entry_reason": why,
                    "entry_score": ctx.get("token_score") if ctx else None,
                    "entry_signature": t.source_signature,
                    "exit_reason": None,
                    "exit_reason_raw": None,
                    "last_trade_at": t.created_at,
                }
                active[t.token_mint] = sess
            sess["cost_sol"] += float(t.sol_amount or 0.0)
            sess["qty"] += float(t.token_amount or 0.0)
            sess["buy_count"] += 1
            sess["last_trade_at"] = t.created_at
        elif t.side == "sell":
            sess = active.get(t.token_mint)
            if not sess:
                sess = {
                    "token_mint": t.token_mint,
                    "token": _token_meta(db, t.token_mint),
                    "status": "closed",
                    "entry_time": None,
                    "exit_time": t.created_at,
                    "entry_price_sol": None,
                    "exit_price_sol": t.price_sol,
                    "cost_sol": 0.0,
                    "proceeds_sol": float(t.sol_amount or 0.0),
                    "qty": float(t.token_amount or 0.0),
                    "pnl_sol": float(t.realized_pnl_sol or 0.0),
                    "pnl_pct": None,
                    "hold_minutes": None,
                    "buy_count": 0,
                    "sell_count": 1,
                    "entry_reason": "Önceki alım kaydı bulunamadı",
                    "entry_score": None,
                    "entry_signature": t.source_signature,
                    "exit_reason": _exit_reason(t.reason),
                    "exit_reason_raw": t.reason,
                    "last_trade_at": t.created_at,
                }
                sessions.append(sess)
                continue
            sess["proceeds_sol"] += float(t.sol_amount or 0.0)
            sess["pnl_sol"] += float(t.realized_pnl_sol or 0.0)
            sess["sell_count"] += 1
            sess["exit_time"] = t.created_at
            sess["exit_price_sol"] = t.price_sol
            sess["exit_reason"] = _exit_reason(t.reason)
            sess["exit_reason_raw"] = t.reason
            sess["last_trade_at"] = t.created_at
            if not bool(t.is_open):
                sess["status"] = "closed"
                if sess.get("entry_time"):
                    sess["hold_minutes"] = round((t.created_at - sess["entry_time"]).total_seconds() / 60.0, 2)
                if sess["cost_sol"] > 0:
                    sess["pnl_pct"] = round(sess["pnl_sol"] / sess["cost_sol"], 4)
                sessions.append(sess)
                active.pop(t.token_mint, None)

    sessions.extend(active.values())
    sessions.sort(key=lambda s: s.get("last_trade_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return sessions[:limit]


def _decision_feed(db: Session, minutes: int, limit: int = 80, since: datetime | None = None) -> tuple[list[dict[str, Any]], Counter[str], dict[str, int]]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    if since is not None and since > cutoff:
        cutoff = since
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.category == "trading", AuditLog.created_at >= cutoff)
        .order_by(AuditLog.id.desc())
        .limit(6000)
        .all()
    )
    feed: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    counts = {"total": 0, "opened": 0, "blocked": 0, "exit": 0, "info": 0}
    for r in rows:
        ctx = r.context or {}
        msg = r.message or ""
        if not _is_ai_context(ctx, msg):
            continue
        action = _decision_action(msg, ctx)

        # Karar merkezi teknik bilgi gürültüsünü değil, gerçek kararları sayar.
        # Huni ise sadece ALMADI sebeplerini göstermelidir; açık işlemler ve
        # çıkışlar sebep çubuklarına karışmaz.
        if action == "info":
            continue

        counts["total"] += 1
        counts[action if action in counts else "info"] += 1
        raw = ctx.get("reason") or ctx.get("blocked") or ctx.get("trade_blocked") or ctx.get("exit_reason") or msg
        reason = _reason_text(raw, msg)
        bucket = "İşlem açıldı" if action == "opened" else _bucket_reason(reason)
        if action == "exit":
            bucket = "Çıkış: " + _bucket_reason(reason)
        if action == "blocked":
            reasons[bucket] += 1
        if len(feed) < limit:
            feed.append({
                "id": r.id,
                "action": action,
                "level": r.level,
                "message": msg,
                "reason": reason,
                "bucket": bucket,
                "token": ctx.get("token"),
                "wallet": ctx.get("wallet"),
                "token_score": ctx.get("token_score"),
                "pnl_sol": ctx.get("pnl_sol"),
                "pnl_pct": ctx.get("pnl_pct"),
                "mode": ctx.get("mode"),
                "signature": ctx.get("signature"),
                "tape": ctx.get("tape"),
                "early_quality": ctx.get("early_quality"),
                "created_at": r.created_at,
            })
    return feed, reasons, counts


def _recommendations(summary: dict[str, Any], reasons: Counter[str]) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    total = max(1, int(summary.get("decisions", 0) or 0))
    opened = int(summary.get("opened_decisions", 0) or 0)
    win_rate = float(summary.get("win_rate") or 0)
    pnl = float(summary.get("realized_pnl_sol") or 0)
    if opened == 0 and total > 20:
        recs.append({"level": "warn", "title": "AI çok seçici", "text": "Son pencerede çok karar var ama alım yok. En büyük huni sebebine göre fiyat/skor/likidite tarafını incele."})
    if opened > 25:
        recs.append({"level": "warn", "title": "AI fazla işlem açıyor", "text": "İşlem sayısı yüksekse slippage ve rug riski büyür. Risk profilini Güvenli yap veya paper miktarını düşük tut."})
    if summary.get("closed_trades", 0) >= 8 and win_rate < 0.35:
        recs.append({"level": "bad", "title": "Win rate zayıf", "text": "AI çıkış motoru veya giriş skoru gevşek olabilir. En kötü işlemlerin exit sebebine bak."})
    if summary.get("closed_trades", 0) >= 5 and pnl < 0:
        recs.append({"level": "bad", "title": "Paper PnL negatif", "text": "Canlı AI kilidini açma. Önce Neden Almadım hunisi ve exit sebeplerini düzelt."})
    top_reason = reasons.most_common(1)
    if top_reason:
        recs.append({"level": "info", "title": "En büyük blok sebebi", "text": f"{top_reason[0][0]}: {top_reason[0][1]} kez. AI'ın nerede takıldığını en hızlı buradan anlarsın."})
    if not recs:
        recs.append({"level": "good", "title": "Veri birikiyor", "text": "AI karar merkezi stabil. En az 24 saat paper sonucundan sonra canlı kilit değerlendirilmeli."})
    return recs[:5]


def ai_decision_center(db: Session, minutes: int = 60, limit: int = 50) -> dict[str, Any]:
    risk = get_setting(db, "risk")
    baseline_since = _baseline_since(db)
    sessions = _build_sessions(db, limit=limit, since=baseline_since)
    closed = [s for s in sessions if s.get("status") == "closed"]
    open_sessions = [s for s in sessions if s.get("status") == "open"]
    wins = [s for s in closed if float(s.get("pnl_sol") or 0) > 0]
    losses = [s for s in closed if float(s.get("pnl_sol") or 0) < 0]
    pnl = sum(float(s.get("pnl_sol") or 0) for s in closed)
    exposure = sum(float(s.get("cost_sol") or 0) for s in open_sessions)
    spent = sum(float(s.get("cost_sol") or 0) for s in sessions)
    feed, reasons, counts = _decision_feed(db, minutes=minutes, since=baseline_since)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    if baseline_since is not None and baseline_since > cutoff:
        cutoff = baseline_since
    ai_buys_window = (
        db.query(PaperTrade)
        .filter(PaperTrade.wallet_address == "AI_TRADE", PaperTrade.side == "buy", PaperTrade.created_at >= cutoff)
        .count()
    )
    # Bazı eski build'lerde AI alım audit logu açılmasına rağmen "AÇILDI"
    # Türkçe karakter sınıflandırması yüzünden opened sayılmıyordu. Alım sayısında
    # gerçek kaynak PaperTrade buy satırıdır; audit yalnızca açıklama/feed içindir.
    opened_count = max(int(counts.get("opened", 0) or 0), int(ai_buys_window or 0))
    blocked_count = int(counts.get("blocked", 0) or 0)
    decision_total = opened_count + blocked_count
    exit_counts = Counter(_exit_reason(s.get("exit_reason_raw") or s.get("exit_reason")) for s in closed)
    avg_hold = None
    holds = [float(s["hold_minutes"]) for s in closed if s.get("hold_minutes") is not None]
    if holds:
        avg_hold = round(sum(holds) / len(holds), 2)
    best = max(closed, key=lambda s: float(s.get("pnl_sol") or 0), default=None)
    worst = min(closed, key=lambda s: float(s.get("pnl_sol") or 0), default=None)
    summary = {
        "strategy_mode": risk.get("strategy_mode", "copy"),
        "trade_mode": risk.get("mode", "paper"),
        "ai_live_enabled": bool(risk.get("ai_live_enabled", False)),
        "ai_auto_manage": risk.get("ai_auto_manage", True),
        "ai_risk_profile": risk.get("ai_risk_profile", "balanced"),
        "window_minutes": minutes,
        "baseline_at": baseline_since.isoformat() if baseline_since else None,
        "decisions": decision_total,
        "opened_decisions": opened_count,
        "blocked_decisions": blocked_count,
        "exit_decisions": counts["exit"],
        "paper_sessions": len(sessions),
        "closed_trades": len(closed),
        "open_positions": len(open_sessions),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3) if closed else 0.0,
        "realized_pnl_sol": round(pnl, 6),
        "open_exposure_sol": round(exposure, 6),
        "paper_spent_sol": round(spent, 6),
        "avg_hold_minutes": avg_hold,
        "best_pnl_sol": round(float(best.get("pnl_sol") or 0), 6) if best else 0.0,
        "worst_pnl_sol": round(float(worst.get("pnl_sol") or 0), 6) if worst else 0.0,
    }
    # --- AI PAPER KARNE: "canlıya hazır mı?" sorusuna ölçülebilir cevap ---
    gross_win = sum(float(s.get("pnl_sol") or 0) for s in wins)
    gross_loss = abs(sum(float(s.get("pnl_sol") or 0) for s in losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    med_hold = None
    if holds:
        hs = sorted(holds)
        med_hold = round(hs[len(hs) // 2], 1)
    win_rate = summary["win_rate"]
    criteria = [
        {"key": "sample", "label": "Yeterli örneklem (≥25 kapanan işlem)",
         "ok": len(closed) >= 25, "value": len(closed)},
        {"key": "pnl", "label": "Dönem PnL pozitif",
         "ok": pnl > 0, "value": round(pnl, 4)},
        {"key": "edge", "label": "Kenar var (isabet ≥%40 veya profit factor ≥1.3)",
         "ok": (win_rate >= 0.40 or profit_factor >= 1.3), "value": f"wr={win_rate:.0%} pf={profit_factor}"},
        {"key": "tail", "label": "Tek işlem felaketi yok (en kötü ≥ -0.05 SOL)",
         "ok": summary["worst_pnl_sol"] >= -0.05, "value": summary["worst_pnl_sol"]},
    ]
    live_ready = all(c["ok"] for c in criteria)
    if profit_factor >= 1.8 and win_rate >= 0.45:
        grade = "A"
    elif profit_factor >= 1.3 and win_rate >= 0.35:
        grade = "B"
    elif profit_factor >= 1.0:
        grade = "C"
    else:
        grade = "D"
    report = {
        "grade": grade,
        "live_ready": live_ready,
        "criteria": criteria,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "closed_trades": len(closed),
        "realized_pnl_sol": round(pnl, 6),
        "median_hold_minutes": med_hold,
        "best_pnl_sol": summary["best_pnl_sol"],
        "worst_pnl_sol": summary["worst_pnl_sol"],
        "verdict": ("Canlıya hazır görünüyor — küçük bakiyeyle başla." if live_ready
                    else "Henüz canlıya hazır değil — paper biriktirmeye devam."),
    }

    return {
        "summary": summary,
        "report": report,
        "funnel": {
            "top_reasons": [{"reason": k, "count": v, "pct": round(v / max(1, blocked_count), 3)} for k, v in reasons.most_common(12)],
            "counts": {**counts, "opened": opened_count, "blocked": blocked_count, "total": decision_total},
        },
        "exit_breakdown": [{"reason": k, "count": v} for k, v in exit_counts.most_common(10)],
        "sessions": sessions,
        "decision_feed": feed,
        "recommendations": _recommendations(summary, reasons),
        "baseline_at": baseline_since.isoformat() if baseline_since else None,
        "generated_at": datetime.now(timezone.utc),
    }

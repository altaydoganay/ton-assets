"""Veri sağlayıcı sağlık kaydı (in-process, thread-safe).

Her market/chain sağlayıcı çağrısının sonucunu (başarılı/başarısız, gecikme, son
hata) burada biriktiririz. Amaç:

  * "Helius zorunlu değil / çok-sağlayıcılı" felsefesini gözlemlenebilir kılmak —
    hangi sağlayıcı ayakta, hangisi düşmüş panelde görünür.
  * "Kötü/bilinmeyen veriyle işlem yapma" fail-safe'ini beslemek — bir sağlayıcı
    DOWN ise UI uyarır ve (isteğe bağlı) AI-mod alımları duraklatılabilir.

Kayıt PROCESS ömürlüdür (Redis/DB'ye yazmayız): listener/worker her biri kendi
snapshot'ını verir; panel API süreci de kendi çağrılarını sayar. Bu, düşük
gecikme ve sıfır bağımlılık için bilinçli bir tercihtir.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

# Son N çağrının sonucu (True=ok) — "degraded/down" sınıflaması bu pencereye bakar.
_WINDOW = 20
# Üst üste bu kadar başarısızlık => DOWN (tek geçici hata paniğe yol açmasın).
_DOWN_CONSECUTIVE = 5
# Penceredeki başarısızlık oranı bu eşiği aşarsa => DEGRADED.
_DEGRADED_FAIL_RATIO = 0.30

_LOCK = threading.Lock()


@dataclass
class _ProviderStat:
    name: str
    kind: str  # "chain" | "market"
    total: int = 0
    ok_count: int = 0
    fail_count: int = 0
    consecutive_failures: int = 0
    last_ok_ts: float | None = None
    last_fail_ts: float | None = None
    last_error: str | None = None
    last_latency_ms: float | None = None
    ema_latency_ms: float | None = None
    recent: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))


_STATS: dict[str, _ProviderStat] = {}


def _key(name: str, kind: str) -> str:
    return f"{kind}:{name}"


def record(name: str, kind: str, ok: bool, latency_ms: float | None = None,
           error: str | None = None) -> None:
    """Bir sağlayıcı çağrısının sonucunu kaydet. Asla exception fırlatmaz —
    gözlem katmanı asıl akışı bozmamalı."""
    try:
        k = _key(name, kind)
        now = time.time()
        with _LOCK:
            st = _STATS.get(k)
            if st is None:
                st = _ProviderStat(name=name, kind=kind)
                _STATS[k] = st
            st.total += 1
            st.recent.append(bool(ok))
            if latency_ms is not None:
                st.last_latency_ms = float(latency_ms)
                st.ema_latency_ms = (
                    float(latency_ms) if st.ema_latency_ms is None
                    else 0.7 * st.ema_latency_ms + 0.3 * float(latency_ms)
                )
            if ok:
                st.ok_count += 1
                st.consecutive_failures = 0
                st.last_ok_ts = now
            else:
                st.fail_count += 1
                st.consecutive_failures += 1
                st.last_fail_ts = now
                if error:
                    st.last_error = str(error)[:300]
    except Exception:  # noqa: BLE001 — gözlem katmanı asla patlamamalı
        pass


def _status_for(st: _ProviderStat) -> str:
    if st.total == 0:
        return "unknown"
    recent = list(st.recent)
    if st.consecutive_failures >= _DOWN_CONSECUTIVE:
        return "down"
    if len(recent) >= 3 and not any(recent):
        return "down"
    if recent:
        fail_ratio = recent.count(False) / len(recent)
        if fail_ratio > _DEGRADED_FAIL_RATIO:
            return "degraded"
    return "ok"


def _snapshot_one(st: _ProviderStat) -> dict:
    recent = list(st.recent)
    return {
        "name": st.name,
        "kind": st.kind,
        "status": _status_for(st),
        "total": st.total,
        "ok": st.ok_count,
        "fail": st.fail_count,
        "consecutive_failures": st.consecutive_failures,
        "recent_fail_ratio": (recent.count(False) / len(recent)) if recent else None,
        "last_ok_ts": st.last_ok_ts,
        "last_fail_ts": st.last_fail_ts,
        "last_error": st.last_error,
        "last_latency_ms": round(st.last_latency_ms, 1) if st.last_latency_ms is not None else None,
        "avg_latency_ms": round(st.ema_latency_ms, 1) if st.ema_latency_ms is not None else None,
    }


def snapshot() -> list[dict]:
    """Tüm sağlayıcıların anlık sağlık görüntüsü (kind, sonra ada göre sıralı)."""
    with _LOCK:
        stats = list(_STATS.values())
    out = [_snapshot_one(st) for st in stats]
    out.sort(key=lambda d: (d["kind"], d["name"]))
    return out


def overall_status() -> str:
    """Tüm sağlayıcıların en kötü durumu: down > degraded > ok > unknown.

    En az bir market VE bir chain sağlayıcı 'down' ise sistem güvenilir veri
    üretemiyor demektir; UI bunu üst düzey uyarı olarak gösterir."""
    snap = snapshot()
    if not snap:
        return "unknown"
    order = {"down": 3, "degraded": 2, "ok": 1, "unknown": 0}
    worst = max((order.get(s["status"], 0) for s in snap), default=0)
    for label, rank in order.items():
        if rank == worst:
            return label
    return "unknown"


def market_data_reliable() -> bool:
    """Fiyat verisi güvenilir mi? En az bir market sağlayıcı 'down' DEĞİLSE True.

    Fail-safe gate'ler için: hiçbir market sağlayıcı ayakta değilse (hepsi down)
    canlı/AI alımı yeni pozisyon açmamalı. Kayıt yoksa (henüz çağrı yapılmadı)
    True döner — mevcut per-trade fiyat kontrolleri zaten koruyor."""
    market = [s for s in snapshot() if s["kind"] == "market"]
    if not market:
        return True
    return any(s["status"] != "down" for s in market)


def reset() -> None:
    """Testler için tüm kaydı temizle."""
    with _LOCK:
        _STATS.clear()

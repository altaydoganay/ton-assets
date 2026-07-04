"""AI Pump.fun avcısı için 8 bileşenli token skoru (100 üzerinden).

Kullanıcı stratejisindeki ağırlıklar:
  organic_buyers   20  — organik erken alıcı kalitesi (tape: farklı alıcı, hız, tek-cüzdan)
  momentum         20  — momentum hızı ve fiyat davranışı (tape: net SOL, al/sat dengesi)
  holder_dist      15  — holder dağılımı (top10 / insider / holder sayısı)
  dev_behavior     15  — dev/creator davranışı (rugger, rug oranı, dev satışı)
  bot_ratio        10  — bot/sniper oranı (metrics sniper_ratio ya da tek-cüzdan proxy)
  sellability      10  — satılabilirlik ve çıkış kalitesi (veto + gerçek satışlar)
  curve_progress    5  — bonding curve ilerleme hızı (curve_sol / yaş)
  metadata          5  — isim / sembol / logo (narrative) varlığı

Veri yoksa ilgili bileşen NÖTR (~50-60) döner; kör ceza vermez. Böylece token
tape ile olgunlaştıkça skor gerçekçileşir. Bantlar (giriş kararı):
  0-69 alma · 70-79 izle · 80-87 scout · 88-94 confirm · 95+ güçlü scout.

Bu skor YALNIZCA AI modunda kullanılır; copy scorer (score_token) değişmez.
"""
from __future__ import annotations

WEIGHTS = {
    "organic_buyers": 20.0,
    "momentum": 20.0,
    "holder_dist": 15.0,
    "dev_behavior": 15.0,
    "bot_ratio": 10.0,
    "sellability": 10.0,
    "curve_progress": 5.0,
    "metadata": 5.0,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _pct(v: float) -> float:
    """0-1 kesir olarak saklanmış değeri yüzdeye çevir (zaten % ise dokunma)."""
    v = float(v or 0.0)
    return v * 100.0 if 0.0 < v <= 1.0 else v


def band_for(total: float) -> str:
    if total >= 95:
        return "strong"
    if total >= 88:
        return "confirm"
    if total >= 80:
        return "scout"
    if total >= 70:
        return "watch"
    return "reject"


def score_ai_token(metrics: dict | None, tape: dict | None,
                   age_seconds: float = 0.0, sellable: bool = True) -> dict:
    m = metrics or {}
    t = tape or {}
    ntr = int(t.get("trades", 0) or 0)
    have_tape = ntr >= 4

    # 1) organik erken alıcı (20)
    if have_tape:
        ub = int(t.get("unique_buyers", 0) or 0)
        b30 = int(t.get("buyers_first_30s", 0) or 0)
        top = float(t.get("top_buyer_share", 0.0) or 0.0)
        s1 = 40.0 + min(30.0, ub * 2.5) + min(15.0, b30 * 3.0)
        s1 -= 30.0 if top >= 0.7 else (15.0 if top >= 0.5 else 0.0)
        s1 = _clamp(s1)
    else:
        s1 = 50.0

    # 2) momentum / fiyat davranışı (20)
    if have_tape:
        net = float(t.get("net_sol", 0.0) or 0.0)
        bsr = float(t.get("buy_sell_ratio", 0.0) or 0.0)
        s2 = 45.0 + _clamp(net * 4.0, -20.0, 30.0)
        s2 += 10.0 if 1.2 <= bsr <= 6.0 else (0.0 if bsr > 0 else -10.0)
        s2 = _clamp(s2)
    else:
        s2 = 50.0

    # 3) holder dağılımı (15)
    top10 = _pct(m.get("top10_pct"))
    insider = _pct(m.get("insider_supply_pct"))
    holders = int(m.get("unique_holders") or m.get("holder_count") or 0)
    if top10 or insider or holders:
        s3 = 100.0 - top10 * 0.6 - insider * 0.8
        if holders and holders < 30:
            s3 -= (1.0 - holders / 30.0) * 25.0
        s3 = _clamp(s3)
    else:
        s3 = 55.0

    # 4) dev / creator davranışı (15)
    has_creator = any(k in m for k in ("creator_is_rugger", "creator_rug_ratio", "creator_prior_tokens"))
    dev_sold = bool(t.get("dev_sold") or m.get("dev_sold"))
    if m.get("creator_is_rugger"):
        s4 = 0.0
    elif has_creator or dev_sold:
        s4 = 100.0 - float(m.get("creator_rug_ratio") or 0.0) * 100.0
        if dev_sold:
            s4 -= 45.0
        if not int(m.get("creator_prior_tokens") or 0):
            s4 -= 12.0
        s4 = _clamp(s4)
    else:
        s4 = 60.0  # bilgi yok → hafif belirsizlik

    # 5) bot / sniper oranı (10)
    sniper = _pct(m.get("sniper_ratio"))
    if sniper > 0:
        s5 = _clamp(100.0 - sniper * 1.2)
    elif have_tape:
        top = float(t.get("top_buyer_share", 0.0) or 0.0)
        s5 = _clamp(100.0 - top * 80.0)   # yoğunlaşma ~ bot/sniper proxy
    else:
        s5 = 55.0

    # 6) satılabilirlik ve çıkış kalitesi (10)
    if not sellable:
        s6 = 0.0
    elif have_tape:
        sells = int(t.get("sells", 0) or 0)
        buys = int(t.get("buys", 0) or 0)
        s6 = 100.0 if sells > 0 else (30.0 if buys >= 6 else 70.0)
    else:
        s6 = 70.0

    # 7) bonding curve ilerleme hızı (5)
    curve = float(m.get("curve_sol_est") or 0.0)
    if curve > 0 and age_seconds > 30:
        rate = curve / (age_seconds / 60.0)   # SOL/dk
        if 1.0 <= rate <= 40.0:
            s7 = 90.0
        elif rate > 40.0:
            s7 = 50.0   # tek mumda şişme
        else:
            s7 = 45.0   # sürünüyor
    else:
        s7 = 50.0

    # 8) metadata / narrative (5)
    has_name = bool(m.get("name"))
    has_sym = bool(m.get("symbol"))
    has_img = bool(m.get("image") or m.get("image_url") or m.get("logo"))
    s8 = _clamp(40.0 + (20.0 if has_name else 0.0) + (20.0 if has_sym else 0.0) + (20.0 if has_img else 0.0))

    subs = {
        "organic_buyers": s1, "momentum": s2, "holder_dist": s3, "dev_behavior": s4,
        "bot_ratio": s5, "sellability": s6, "curve_progress": s7, "metadata": s8,
    }
    total = round(sum(subs[k] * WEIGHTS[k] for k in subs) / 100.0, 1)
    breakdown = {
        k: {"value": round(subs[k], 1), "weight": WEIGHTS[k],
            "points": round(subs[k] * WEIGHTS[k] / 100.0, 1)}
        for k in subs
    }
    return {"total": total, "band": band_for(total), "breakdown": breakdown,
            "have_tape": have_tape}

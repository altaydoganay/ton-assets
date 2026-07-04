"""Erken-token 'trade tape' — mint başına ilk dakikaların canlı al/sat akışını
hafızada tutan hafif, thread-safe halka tampon.

Amaç: yeni pump.fun tokenlerinin ilk saniyelerdeki DAVRANIŞINI ölçmek —
kaç FARKLI alıcı geldi, alım/satım dengesi, tek cüzdan yoğunluğu, net SOL akışı,
dev'in satıp satmadığı. Bu sinyaller:
  - AI skorlamasının 'organik erken alıcı / momentum / bot oranı' bileşenlerini,
  - kademeli girişin (scout→confirm→scale) 'sağlıklı kalıyor mu' kararını,
  - hard-reject kurallarını (tek cüzdan pump, sadece bot, sell yok) besler.

Kayıt listener sürecinde (WS akışından) yapılır; türetilmiş sinyaller
`token.metrics["tape"]` alanına yazılıp diğer süreçler (skorlama, pozisyon
yöneticisi) tarafından okunur. Ekstra API/kota gerektirmez — mevcut akışı okur.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, defaultdict

WSOL_MINT = "So11111111111111111111111111111111111111112"


class TokenTape:
    def __init__(self, window_seconds: float = 120.0, max_mints: int = 8000,
                 max_per_mint: int = 500):
        self.window = float(window_seconds)
        self.max_mints = int(max_mints)
        self.max_per_mint = int(max_per_mint)
        # mint -> list[(ts, trader, dir(+1/-1), sol_abs)]
        self._d: "OrderedDict[str, list]" = OrderedDict()
        self._lock = threading.Lock()

    def record(self, mint: str, trader: str, side: str, sol: float, ts: float | None = None) -> None:
        if not mint or mint == WSOL_MINT:
            return
        ts = ts or time.time()
        d = 1 if side == "buy" else -1
        with self._lock:
            buf = self._d.get(mint)
            if buf is None:
                buf = []
                self._d[mint] = buf
            buf.append((float(ts), str(trader or ""), d, abs(float(sol or 0.0))))
            if len(buf) > self.max_per_mint:
                del buf[0:len(buf) - self.max_per_mint]
            self._d.move_to_end(mint, last=True)
            while len(self._d) > self.max_mints:
                self._d.popitem(last=False)

    def _rows(self, mint: str, now: float) -> list:
        cutoff = now - self.window
        with self._lock:
            buf = self._d.get(mint)
            if not buf:
                return []
            return [r for r in buf if r[0] >= cutoff]

    def signals(self, mint: str, now: float | None = None) -> dict | None:
        """Türetilmiş erken-davranış sinyalleri (yoksa None)."""
        now = now or time.time()
        rows = self._rows(mint, now)
        if not rows:
            return None
        first_ts = min(r[0] for r in rows)
        age = max(0.0, now - first_ts)
        buys = [r for r in rows if r[2] > 0]
        sells = [r for r in rows if r[2] < 0]
        buyers = {r[1] for r in buys if r[1]}
        buyers_30 = {r[1] for r in buys if r[1] and (r[0] - first_ts) <= 30.0}
        buy_sol = sum(r[3] for r in buys)
        sell_sol = sum(r[3] for r in sells)
        by_wallet: dict[str, float] = defaultdict(float)
        for r in buys:
            if r[1]:
                by_wallet[r[1]] += r[3]
        top_share = (max(by_wallet.values()) / buy_sol) if (buy_sol > 0 and by_wallet) else 0.0
        return {
            "age_seconds": round(age, 1),
            "trades": len(rows),
            "buys": len(buys),
            "sells": len(sells),
            "unique_buyers": len(buyers),
            "buyers_first_30s": len(buyers_30),
            "buy_sol": round(buy_sol, 4),
            "sell_sol": round(sell_sol, 4),
            "net_sol": round(buy_sol - sell_sol, 4),
            "buy_sell_ratio": round(len(buys) / max(1, len(sells)), 2),
            "top_buyer_share": round(top_share, 3),
        }

    def dev_sold(self, mint: str, creator: str | None, now: float | None = None) -> bool:
        """Creator cüzdanı bu tokende satış yaptı mı (dev dump sinyali)."""
        if not creator:
            return False
        now = now or time.time()
        return any(r[2] < 0 and r[1] == creator for r in self._rows(mint, now))

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


# Süreç-içi tekil (listener süreci besler; sinyaller DB'ye flush edilir)
TAPE = TokenTape()


def early_quality_score(sig: dict | None) -> float:
    """Erken davranıştan 0-100 kaba 'organik/momentum' kalite skoru.

    Yeterli örnek yoksa (çok taze) 50 (nötr) döner; kör ceza vermez. Yüksek =
    çok farklı alıcı + sağlıklı alım/satım + tek cüzdan yoğunluğu düşük.
    """
    if not sig or int(sig.get("trades", 0)) < 4:
        return 50.0
    score = 40.0
    ub = int(sig.get("unique_buyers", 0))
    score += min(24.0, ub * 2.0)                     # farklı alıcı çeşitliliği
    score += min(10.0, int(sig.get("buyers_first_30s", 0)) * 2.0)  # erken hız
    bsr = float(sig.get("buy_sell_ratio", 0) or 0)
    score += 10.0 if 1.2 <= bsr <= 6.0 else (4.0 if bsr > 0 else 0.0)  # sağlıklı denge
    top = float(sig.get("top_buyer_share", 0) or 0)
    score -= 26.0 if top >= 0.7 else (14.0 if top >= 0.5 else 0.0)     # tek cüzdan cezası
    if int(sig.get("sells", 0)) == 0 and int(sig.get("buys", 0)) >= 6:
        score -= 12.0                                # hiç satış yok = honeypot şüphesi
    return max(0.0, min(100.0, round(score, 1)))

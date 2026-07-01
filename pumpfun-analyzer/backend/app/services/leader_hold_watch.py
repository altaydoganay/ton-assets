"""Lider elde tutma bekçisi.

Sorun: canlı WS/poll liderin SELL olayını kaçırırsa bizim copy pozisyonumuz açık
kalabilir. Bu servis açık copy pozisyonlarını periyodik kontrol eder: kopyalanan
lider cüzdan ilgili token'ı artık taşımıyorsa bizim pozisyonu de acil kapatır.

Önemli kararlar:
- Kaynak gerçek token account snapshot'ıdır (processed commitment). Eski transfer
  geçmişi kullanılmaz; çünkü satılmış tokenleri varmış gibi gösterebilir.
- Veri okunamazsa fail-safe: SATMAZ, loglar. Yanlış sıfırdan ziyade veri hatasını
  ayırır.
- Lider bakiyesi dust/çok küçük kaldıysa çıkış sayılır.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpportal import PumpPortalTrader
from ..models import AuditLog, LiveTrade, PaperTrade, Swap
from ..trading.engine import TradeContext, LiveTradingNotConfigured
from .live_flow import _reconcile_live_trade, get_engine
from .settings_service import get_setting, set_setting
from .wallet_portfolio import resolve_trading_wallet_address

logger = logging.getLogger(__name__)


@dataclass
class MirroredPosition:
    mode: str  # live | paper
    wallet_address: str
    token_mint: str
    qty: float
    cost_sol: float
    first_buy_at: datetime | None
    latest_buy_at: datetime | None
    leader_bought_token_amount: float
    buy_trade_ids: list[int]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_token_account_amount(row: dict[str, Any], mint: str) -> float:
    try:
        info = row["account"]["data"]["parsed"]["info"]
        if info.get("mint") != mint:
            return 0.0
        amount = info.get("tokenAmount") or {}
        ui_amount = amount.get("uiAmount")
        if ui_amount is None:
            ui_amount = amount.get("uiAmountString")
        return max(0.0, float(ui_amount or 0.0))
    except (KeyError, TypeError, ValueError):
        return 0.0


def token_balance(chain: ChainProvider, owner: str, mint: str) -> tuple[float, dict[str, Any]]:
    """Owner'ın ilgili mint için anlık token bakiyesini oku."""
    getter = getattr(chain, "get_token_accounts_by_owner", None)
    if getter is None:
        raise RuntimeError("Zincir sağlayıcı token account okumasını desteklemiyor")
    try:
        accounts = getter(owner, commitment="processed")
    except TypeError:
        accounts = getter(owner)
    balance = 0.0
    rows = 0
    for row in accounts or []:
        rows += 1
        balance += _parse_token_account_amount(row, mint)
    return balance, {"token_account_rows": rows, "commitment": "processed"}


def _balances_by_mint(chain: ChainProvider, owner: str) -> dict[str, float]:
    """Owner'ın tüm SPL token bakiyelerini mint -> amount olarak oku."""
    getter = getattr(chain, "get_token_accounts_by_owner", None)
    if getter is None:
        raise RuntimeError("Zincir sağlayıcı token account okumasını desteklemiyor")
    try:
        accounts = getter(owner, commitment="processed")
    except TypeError:
        accounts = getter(owner)
    balances: dict[str, float] = {}
    for row in accounts or []:
        try:
            mint = row["account"]["data"]["parsed"]["info"].get("mint")
        except Exception:  # noqa: BLE001
            mint = None
        if not mint:
            continue
        balances[mint] = balances.get(mint, 0.0) + _parse_token_account_amount(row, mint)
    return balances


def _ghost_close_position(db: Session, pos: MirroredPosition, *, reason: str) -> dict[str, Any]:
    """DB açık sanıyor ama gerçek trading cüzdanında token yoksa pozisyonu temizle.

    PumpPortal'a satış emri göndermek yerine sentetik bir live sell kaydı ekler.
    Amaç muhasebeyi kapatıp watchdog'un aynı pozisyon için sürekli sell denemesi
    ve kırmızı hata üretmesini engellemektir. Gerçek zincirde satış yapılmaz.
    """
    row = LiveTrade(
        wallet_address=pos.wallet_address,
        token_mint=pos.token_mint,
        side="sell",
        sol_amount=0.0,
        token_amount=max(float(pos.qty or 0.0), 0.0),
        price_sol=0.0,
        fee_sol=0.0,
        status="confirmed",
        signature=None,
        error=(reason[:240] if reason else "ghost position closed"),
        is_open=False,
        realized_pnl_sol=0.0,
        source_signature=f"leader-watch-ghost-{int(_now().timestamp())}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"closed": True, "ghost": True, "trade_id": row.id, "mode": pos.mode, "reason": reason}


def _looks_like_missing_own_token_error(err: Any) -> bool:
    text = str(err or "").lower()
    needles = (
        "could not find account",
        "get token account balance",
        "token account balance",
        "token account not found",
        "account not found",
        "no token account",
        "insufficient token",
    )
    return any(n in text for n in needles)


def _leader_bought_amount(db: Session, signatures: list[str | None], fallback: float) -> float:
    sigs = [s for s in signatures if s]
    if not sigs:
        return fallback
    rows = db.query(Swap).filter(Swap.signature.in_(sigs), Swap.side == "buy").all()
    amount = sum(float(r.token_amount or 0.0) for r in rows)
    return amount if amount > 0 else fallback


def _open_positions_from_trades(db: Session, model, mode: str) -> list[MirroredPosition]:
    q = db.query(model).filter(model.status != "failed") if model is LiveTrade else db.query(model)
    rows = q.order_by(model.created_at.asc(), model.id.asc()).all()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r.wallet_address, r.token_mint)
        p = grouped.setdefault(key, {
            "mode": mode,
            "wallet_address": r.wallet_address,
            "token_mint": r.token_mint,
            "qty": 0.0,
            "cost_sol": 0.0,
            "first_buy_at": None,
            "latest_buy_at": None,
            "buy_ids": [],
            "buy_sigs": [],
            "fallback_leader_tokens": 0.0,
        })
        if r.side == "buy":
            p["qty"] += float(r.token_amount or 0.0)
            p["cost_sol"] += float(r.sol_amount or 0.0)
            p["first_buy_at"] = p["first_buy_at"] or r.created_at
            p["latest_buy_at"] = r.created_at
            p["buy_ids"].append(int(r.id))
            p["buy_sigs"].append(getattr(r, "source_signature", None))
            # Paper/LiveTrade token_amount bizim tahmini miktarımızdır; lider miktarı
            # bulunamazsa sadece oran filtresini devre dışı bırakmamak için fallback.
            p["fallback_leader_tokens"] += float(getattr(r, "token_amount", 0.0) or 0.0)
        elif p["qty"] > 0:
            sold_qty = min(p["qty"], float(r.token_amount or 0.0))
            frac = sold_qty / p["qty"] if p["qty"] > 0 else 0.0
            p["cost_sol"] -= p["cost_sol"] * frac
            p["qty"] -= sold_qty
            if p["qty"] <= 1e-9:
                p["qty"] = 0.0
                p["cost_sol"] = 0.0
    out: list[MirroredPosition] = []
    for p in grouped.values():
        if p["qty"] <= 1e-9:
            continue
        if str(p.get("wallet_address") or "") == "AI_TRADE":
            continue  # AI Trade pozisyonunda lider cüzdan yok; çıkışı TP/SL/trailing yönetir.
        leader_amount = _leader_bought_amount(db, p["buy_sigs"], p["fallback_leader_tokens"])
        out.append(MirroredPosition(
            mode=p["mode"], wallet_address=p["wallet_address"], token_mint=p["token_mint"],
            qty=float(p["qty"]), cost_sol=float(p["cost_sol"]),
            first_buy_at=p["first_buy_at"], latest_buy_at=p["latest_buy_at"],
            leader_bought_token_amount=float(leader_amount or 0.0),
            buy_trade_ids=list(p["buy_ids"]),
        ))
    return out


def open_mirrored_positions(db: Session, *, include_paper: bool = False) -> list[MirroredPosition]:
    positions = _open_positions_from_trades(db, LiveTrade, "live")
    if include_paper:
        positions.extend(_open_positions_from_trades(db, PaperTrade, "paper"))
    # En yeni/kritik pozisyonları önce kontrol et.
    positions.sort(key=lambda p: p.latest_buy_at or p.first_buy_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return positions


def _market_price(market: MarketProvider | None, mint: str) -> float:
    if market is None:
        return 0.0
    try:
        md = market.get_token_market(mint)
        if md and getattr(md, "ok", False) and getattr(md, "price_sol", None):
            return float(md.price_sol or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.0


def _state_key(pos: MirroredPosition) -> str:
    return f"{pos.mode}:{pos.wallet_address}:{pos.token_mint}"


def _short(a: str) -> str:
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else a


def _audit(db: Session, level: str, msg: str, context: dict[str, Any]) -> None:
    try:
        db.add(AuditLog(level=level, category="leader_watch", message=msg, context=context))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _should_exit(pos: MirroredPosition, leader_balance: float, risk: dict[str, Any]) -> tuple[bool, str]:
    zero_threshold = float(risk.get("leader_hold_zero_threshold", 1e-9) or 1e-9)
    exit_ratio = float(risk.get("leader_hold_exit_ratio", 0.05) or 0.0)
    if leader_balance <= zero_threshold:
        return True, f"lider token bakiyesi sıfır/dust ({leader_balance:.6g})"
    if pos.leader_bought_token_amount > 0 and exit_ratio > 0:
        limit = pos.leader_bought_token_amount * exit_ratio
        if leader_balance <= limit:
            return True, (
                f"lider bakiyesi alım miktarının %{exit_ratio*100:.1f} altına düştü "
                f"({leader_balance:.6g} <= {limit:.6g})"
            )
    return False, "lider hâlâ tokende"


def _close_position(
    db: Session,
    pos: MirroredPosition,
    *,
    market: MarketProvider | None,
    chain: ChainProvider,
    reason: str,
) -> dict[str, Any]:
    price = _market_price(market, pos.token_mint)
    if pos.mode == "live":
        engine = get_engine(db, signer=PumpPortalTrader())
        ctx = TradeContext(
            wallet_address=pos.wallet_address,
            token_mint=pos.token_mint,
            wallet_score=0.0,
            token_score=0.0,
            token_liquidity_sol=0.0,
            token_sellable=True,
            follow_lag_seconds=0.0,
            market_price_sol=price,
            leader_sol_amount=None,
            source_signature=f"leader-watch-{int(_now().timestamp())}",
        )
        try:
            row = engine.on_leader_sell(db, ctx, leader_sell_fraction=1.0)
        except LiveTradingNotConfigured as exc:
            return {"closed": False, "error": str(exc), "mode": pos.mode}
        if row and getattr(row, "status", None) != "failed":
            try:
                _reconcile_live_trade(db, chain, getattr(row, "id", None))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Leader-watch reconcile hata: %s", exc)
            return {"closed": True, "trade_id": getattr(row, "id", None), "signature": getattr(row, "signature", None), "mode": pos.mode}
        return {"closed": False, "error": getattr(row, "error", "satış emri oluşturulamadı"), "mode": pos.mode}

    # Paper ölçümde de missed sell simüle edilsin. Gerçek para yok. Risk motorunun
    # o anki mode'u live olabilir; bu yüzden paper kapatmayı doğrudan PaperTrade
    # kaydıyla yaparız, asla canlı satış yoluna düşmeyiz.
    proceeds = float(pos.qty or 0.0) * float(price or 0.0)
    pnl = proceeds - float(pos.cost_sol or 0.0) if price > 0 else 0.0
    row = PaperTrade(
        wallet_address=pos.wallet_address,
        token_mint=pos.token_mint,
        side="sell",
        sol_amount=proceeds,
        token_amount=pos.qty,
        price_sol=price,
        fee_sol=0.0,
        realized_pnl_sol=pnl,
        is_open=False,
        reason="leader-hold-watch (paper)",
        source_signature=f"leader-watch-{int(_now().timestamp())}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"closed": True, "trade_id": row.id, "mode": pos.mode}


def run_leader_hold_watch(
    db: Session,
    chain: ChainProvider,
    market: MarketProvider | None = None,
    *,
    max_positions: int | None = None,
) -> dict[str, Any]:
    """Açık copy pozisyonlarında lider hâlâ token tutuyor mu kontrol et."""
    risk = get_setting(db, "risk")
    if not bool(risk.get("leader_hold_watch_enabled", True)):
        return {"enabled": False, "checked": 0, "closed": 0}

    include_paper = bool(risk.get("leader_hold_watch_paper", False))
    positions = open_mirrored_positions(db, include_paper=include_paper)
    limit = int(max_positions or risk.get("leader_hold_max_positions_per_run", 30) or 30)
    grace = int(risk.get("leader_hold_grace_seconds", 20) or 0)
    cooldown = int(risk.get("leader_hold_cooldown_seconds", 20) or 0)
    confirmations_required = max(1, int(risk.get("leader_hold_exit_confirmations", 1) or 1))
    state = dict(get_setting(db, "leader_hold_watch_state") or {})
    now = _now()

    checked = skipped = closed = errors = still_in = ghost_closed = 0
    details: list[dict[str, Any]] = []
    wallet_cache: dict[str, dict[str, float]] = {}
    own_cache: dict[str, dict[str, float]] = {}

    verify_own = bool(risk.get("leader_hold_verify_own_balance", True))
    own_zero_threshold = float(risk.get("leader_hold_own_zero_threshold", risk.get("leader_hold_zero_threshold", 1e-9)) or 1e-9)
    own_confirmations = max(1, int(risk.get("leader_hold_own_zero_confirmations", 2) or 2))
    own_address: str | None = None
    own_address_source = "disabled"
    if verify_own:
        own_address, own_address_source = resolve_trading_wallet_address()

    for pos in positions[:limit]:
        key = _state_key(pos)
        st = dict(state.get(key) or {})
        latest = pos.latest_buy_at or pos.first_buy_at
        if latest:
            latest_aware = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
            age = (now - latest_aware).total_seconds()
            if age < grace:
                skipped += 1
                continue
        try:
            last_action_ts = float(st.get("last_action_ts") or 0.0)
        except (TypeError, ValueError):
            last_action_ts = 0.0
        if last_action_ts and cooldown > 0 and (now.timestamp() - last_action_ts) < cooldown:
            skipped += 1
            continue

        try:
            # ÖNCE kendi trading cüzdanımızda token var mı kontrol et.
            # DB açık pozisyon sanıyor ama gerçek cüzdanda token yoksa satış emri
            # göndermek anlamsızdır; bu stale/ghost pozisyonu temizleriz.
            own_bal: float | None = None
            if pos.mode == "live" and verify_own and own_address:
                if own_address not in own_cache:
                    own_cache[own_address] = _balances_by_mint(chain, own_address)
                own_bal = float(own_cache.get(own_address, {}).get(pos.token_mint, 0.0))
                own_zero_count = int(st.get("own_zero_count") or 0)
                if own_bal <= own_zero_threshold:
                    own_zero_count += 1
                else:
                    own_zero_count = 0
                st.update({
                    "own_wallet_address": own_address,
                    "own_wallet_source": own_address_source,
                    "own_balance": own_bal,
                    "own_zero_count": own_zero_count,
                    "last_checked_at": now.isoformat(),
                    "mode": pos.mode,
                })
                state[key] = st
                if own_zero_count >= own_confirmations:
                    result = _ghost_close_position(
                        db,
                        pos,
                        reason=(
                            "Gerçek trading cüzdanında token yok; "
                            "DB açık pozisyonu stale/ghost olarak temizlendi"
                        ),
                    )
                    st["last_action_ts"] = now.timestamp()
                    st["last_action_at"] = now.isoformat()
                    st["last_action_result"] = result
                    state[key] = st
                    closed += 1
                    ghost_closed += 1
                    _audit(
                        db,
                        "info",
                        f"Ghost live pozisyon temizlendi: {_short(pos.wallet_address)} → {_short(pos.token_mint)}",
                        {
                            "wallet": pos.wallet_address,
                            "token": pos.token_mint,
                            "own_wallet": own_address,
                            "own_balance": own_bal,
                            "result": result,
                        },
                    )
                    details.append({
                        "wallet": pos.wallet_address,
                        "token": pos.token_mint,
                        "own_balance": own_bal,
                        "ghost": True,
                        **result,
                    })
                    continue
                # İlk sıfır okumada panik satışı yapma; bir sonraki tur teyit etsin.
                if own_zero_count > 0:
                    skipped += 1
                    details.append({
                        "wallet": pos.wallet_address,
                        "token": pos.token_mint,
                        "own_balance": own_bal,
                        "ghost_pending": True,
                        "confirmations": f"{own_zero_count}/{own_confirmations}",
                    })
                    continue

            if pos.wallet_address not in wallet_cache:
                # Cüzdan başına tek RPC okuması; aynı liderde çok pozisyon varsa ucuzlar.
                accounts = getattr(chain, "get_token_accounts_by_owner")(pos.wallet_address, commitment="processed")
                balances: dict[str, float] = {}
                for row in accounts or []:
                    try:
                        mint = row["account"]["data"]["parsed"]["info"].get("mint")
                    except Exception:  # noqa: BLE001
                        mint = None
                    if not mint:
                        continue
                    balances[mint] = balances.get(mint, 0.0) + _parse_token_account_amount(row, mint)
                wallet_cache[pos.wallet_address] = balances
            leader_bal = float(wallet_cache.get(pos.wallet_address, {}).get(pos.token_mint, 0.0))
            checked += 1
            should_exit, reason = _should_exit(pos, leader_bal, risk)
            miss_count = int(st.get("exit_signal_count") or 0)
            if should_exit:
                miss_count += 1
            else:
                miss_count = 0
                still_in += 1

            st.update({
                "last_checked_at": now.isoformat(),
                "leader_balance": leader_bal,
                "leader_bought_token_amount": pos.leader_bought_token_amount,
                "exit_signal_count": miss_count,
                "reason": reason,
                "mode": pos.mode,
            })
            state[key] = st

            if not should_exit or miss_count < confirmations_required:
                details.append({"wallet": pos.wallet_address, "token": pos.token_mint, "balance": leader_bal, "exit": False, "reason": reason})
                continue

            result = _close_position(db, pos, market=market, chain=chain, reason=reason)
            st["last_action_ts"] = now.timestamp()
            st["last_action_at"] = now.isoformat()
            st["last_action_result"] = result
            state[key] = st
            if result.get("closed"):
                closed += 1
                _audit(
                    db,
                    "warning",
                    f"Lider tokenden çıktı — pozisyon acil kapatıldı: {_short(pos.wallet_address)} → {_short(pos.token_mint)} ({pos.mode})",
                    {"wallet": pos.wallet_address, "token": pos.token_mint, "reason": reason, "result": result,
                     "leader_balance": leader_bal, "leader_bought_token_amount": pos.leader_bought_token_amount},
                )
            elif pos.mode == "live" and _looks_like_missing_own_token_error(result.get("error")):
                # PumpPortal "token account yok" diyorsa gerçek cüzdanda zaten token
                # yoktur. Bunu hata spam'i yerine ghost close olarak temizle.
                result = _ghost_close_position(
                    db,
                    pos,
                    reason=f"Satış yerine ghost temizlendi: {result.get('error')}",
                )
                closed += 1
                ghost_closed += 1
                _audit(
                    db,
                    "info",
                    f"Ghost live pozisyon temizlendi: {_short(pos.wallet_address)} → {_short(pos.token_mint)}",
                    {"wallet": pos.wallet_address, "token": pos.token_mint, "reason": reason, "result": result,
                     "leader_balance": leader_bal},
                )
            else:
                errors += 1
                _audit(
                    db,
                    "error",
                    f"Lider tokenden çıktı ama pozisyon kapatılamadı: {_short(pos.wallet_address)} → {_short(pos.token_mint)} ({pos.mode})",
                    {"wallet": pos.wallet_address, "token": pos.token_mint, "reason": reason, "result": result,
                     "leader_balance": leader_bal},
                )
            details.append({"wallet": pos.wallet_address, "token": pos.token_mint, "balance": leader_bal, "exit": True, **result})
        except Exception as exc:  # noqa: BLE001
            errors += 1
            st.update({"last_checked_at": now.isoformat(), "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            state[key] = st
            logger.warning("Leader hold watch hata %s/%s: %s", pos.wallet_address, pos.token_mint, exc)

    set_setting(db, "leader_hold_watch_state", state)
    return {
        "enabled": True,
        "positions": len(positions),
        "checked": checked,
        "skipped": skipped,
        "still_in": still_in,
        "closed": closed,
        "ghost_closed": ghost_closed,
        "errors": errors,
        "own_wallet_address_found": bool(own_address),
        "own_wallet_source": own_address_source,
        "as_of": now.isoformat(),
        "details": details[:20],
    }

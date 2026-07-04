"""Canlı olay akışı işleyicisi.

PumpPortal'dan gelen GERÇEK al-sat olayını alır ve görev tanımındaki akışı
uygular:

  1. Olayı `swaps` tablosuna idempotent yazar (canlı olay akışı sayfası).
  2. Cüzdan takipte (puan ≥ eşik) değilse durur.
  3. Tokeni anlık analiz eder; token puanı eşik altındaysa / veto varsa
     bildirim ve işlem YAPILMAZ (işlem öncesi son güvenlik kontrolü).
  4. ALIM ise: signature bazlı dedup → Telegram bildirimi → (ayar açıksa)
     kopya işlem motoru (paper veya canlı PumpPortal Lightning).
  5. SATIM ise: paper/canlı yansıtma (kısmi/tam).

Bildirim ile işlem motoru BAĞIMSIZDIR; işlem Telegram'ı beklemez.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..adapters.base import ChainProvider, MarketProvider
from ..adapters.pumpfun import normalize_rpc_transaction
from ..adapters.pumpportal import PumpPortalTrade, PumpPortalTrader
from ..adapters.registry import build_chain_provider, build_market_provider
from ..config import settings
from ..core.analysis.swap_detection import DetectedSwap, detect_swap
from ..models import AuditLog, LiveTrade, PaperTrade, Token, TokenStatus, Wallet, WalletStatus
from ..notifications.telegram import AlertContent, TelegramNotifier, short_addr
from ..trading.engine import CopyTradeEngine, TradeContext, LiveTradingNotConfigured
from ..trading.risk import RiskConfig
from . import provider_health
from .analysis_service import get_or_create_token
from .pipeline import store_swap
from .settings_service import get_setting, resolve_ai_policy
from .token_analysis import TokenAssessment, assess_token

logger = logging.getLogger(__name__)

_engine: CopyTradeEngine | None = None
_engine_reset_token: str | None = None


def _fresh_market_price(market: MarketProvider, mint: str) -> float:
    try:
        md = market.get_token_market(mint)
        if md and getattr(md, "ok", False) and getattr(md, "price_sol", None):
            return float(md.price_sol or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.0


def _reconcile_live_trade(db: Session, chain: ChainProvider, row_id: int | None) -> None:
    """PumpPortal submitted işleminden sonra gerçek on-chain fill'i DB'ye işler.

    PumpPortal Lightning kesin fill miktarını dönmediği için ilk kayıt tahmindir.
    Signature geldiyse Solana transaction okunur, TRADING_WALLET_ADDRESS üzerindeki
    gerçek swap bulunur ve LiveTrade miktar/fiyat/PnL alanları buna göre düzeltilir.
    """
    if not row_id:
        return
    from ..models import LiveTrade

    def _position_before_trade(token_mint: str, before_id: int) -> tuple[float, float]:
        rows = (
            db.query(LiveTrade)
            .filter(
                LiveTrade.token_mint == token_mint,
                LiveTrade.status != "failed",
                LiveTrade.id < before_id,
            )
            .order_by(LiveTrade.created_at.asc(), LiveTrade.id.asc())
            .all()
        )
        qty = 0.0
        cost = 0.0
        for r in rows:
            if r.side == "buy":
                qty += float(r.token_amount or 0.0)
                cost += float(r.sol_amount or 0.0)
            elif r.side == "sell" and qty > 0:
                sold_qty = min(qty, float(r.token_amount or 0.0))
                frac = sold_qty / qty if qty > 0 else 0.0
                cost -= cost * frac
                qty -= sold_qty
                if qty <= 1e-9:
                    qty = 0.0
                    cost = 0.0
        return qty, cost

    row = db.query(LiveTrade).filter(LiveTrade.id == row_id).first()
    if not row or not row.signature or row.status == "failed":
        return
    trading_wallet = settings.trading_wallet_address
    if not trading_wallet:
        row.error = "Reconcile atlandı: TRADING_WALLET_ADDRESS boş"
        db.commit()
        return
    try:
        raw = chain.get_transaction(row.signature)
        ntx = normalize_rpc_transaction(raw) if raw else None
        swap = detect_swap(ntx, trading_wallet) if ntx else None
    except Exception as exc:  # noqa: BLE001
        row.error = f"Reconcile okunamadı: {type(exc).__name__}"
        db.commit()
        logger.warning("Live reconcile okunamadı %s: %s", row.signature[:8], exc)
        return
    if not swap or swap.token_mint != row.token_mint or swap.side != row.side:
        row.error = "Reconcile eşleşmedi: trading wallet swap bulunamadı"
        db.commit()
        return
    row.sol_amount = float(swap.sol_amount or row.sol_amount or 0.0)
    row.token_amount = float(swap.token_amount or row.token_amount or 0.0)
    row.price_sol = float(swap.price_sol or row.price_sol or 0.0)
    if row.side == "sell":
        qty, cost = _position_before_trade(row.token_mint, row.id)
        sold_qty = min(float(row.token_amount or 0.0), qty) if qty > 0 else float(row.token_amount or 0.0)
        cost_part = (cost * (sold_qty / qty)) if qty > 0 else 0.0
        row.realized_pnl_sol = float(row.sol_amount or 0.0) - cost_part
    row.error = None
    db.commit()


def _audit(db: Session, level: str, message: str, context: dict) -> None:
    """Takip olayının kararını Loglar sayfasına yazar (şeffaflık/ayar için).
    Başarısız olsa bile akışı bozmaz."""
    try:
        db.add(AuditLog(level=level, category="trading", message=message, context=context))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _risk_config(db: Session) -> RiskConfig:
    r = get_setting(db, "risk")
    thresholds = get_setting(db, "thresholds")
    return RiskConfig(
        enabled=bool(r.get("enabled")),
        mode=r.get("mode", "paper"),
        live_confirmed=bool(r.get("live_confirmed")),
        strategy_mode=str(r.get("strategy_mode", "copy")),
        fixed_sol_amount=float(r.get("fixed_sol_amount", 0.05)),
        paper_trade_sol=float(r.get("paper_trade_sol", 0.01)),
        proportional=bool(r.get("proportional")),
        proportional_factor=float(r.get("proportional_factor", 1.0)),
        max_position_sol=float(r.get("max_position_sol", 0.5)),
        max_daily_spend_sol=float(r.get("max_daily_spend_sol", 2.0)),
        max_daily_loss_sol=float(r.get("max_daily_loss_sol", 1.0)),
        max_slippage=float(r.get("max_slippage", 0.15)),
        priority_fee_sol=float(r.get("priority_fee_sol", 0.0005)),
        min_wallet_score=float(r.get("min_wallet_score", thresholds.get("wallet", 70.0))),
        min_token_score=float(r.get("min_token_score", thresholds.get("token", 70.0))),
        token_gate=str(r.get("token_gate", "safety")),
        max_open_positions_per_token=int(r.get("max_open_positions_per_token", 1)),
        max_follow_lag_seconds=int(r.get("max_follow_lag_seconds", 60)),
        max_follow_lag_seconds_paper=int(r.get("max_follow_lag_seconds_paper", 300)),
        min_liquidity_sol=float(r.get("min_liquidity_sol", 5.0)),
        emergency_stop=bool(r.get("emergency_stop")),
        blocked_wallets=list(r.get("blocked_wallets", [])),
        blocked_tokens=list(r.get("blocked_tokens", [])),
        only_wallets=list(r.get("only_wallets", [])),
    )


def _live_wallet_quality_block(wallet: Wallet, risk: dict) -> str | None:
    """Canlı işlemde cüzdan kaynaklı zarar riskini sert engelle.

    Paper/analiz aşamasında geniş ağ izlenebilir; canlıda ise özellikle sniper ve
    çok hızlı satış yapan cüzdanlar kopya gecikmesi yüzünden tepeden aldırır.
    Bu kapı yalnızca BUY için uygulanır; lider sell gelirse pozisyondan çıkış
    engellenmez.
    """
    if not bool(risk.get("block_sniper_wallets_live", True)):
        return None
    m = wallet.metrics or {}

    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(m.get(key) if m.get(key) is not None else default)
        except (TypeError, ValueError):
            return default

    closed = int(_f("closed_positions", 0))
    median_hold = _f("median_hold_seconds", 0.0)
    short_hold = _f("short_hold_ratio", 0.0)
    sniper_conf = _f("sniper_confidence", 0.0)
    scalper_conf = _f("scalper_confidence", 0.0)
    copy_score = _f("copyability_score", 50.0)
    copy_sample = int(_f("copy_sample_size", 0))
    copy_pnl_10 = _f("copy_pnl_10s_sol", 0.0)
    entry_jump_10 = _f("avg_entry_jump_10s", 0.0)
    related_tracked = int(_f("related_tracked_wallet_count", 0))

    min_median = float(risk.get("live_min_median_hold_seconds", 300) or 0)
    max_short = float(risk.get("live_max_short_hold_ratio", 0.45) or 1)
    max_sniper = float(risk.get("live_max_sniper_confidence", 0.45) or 1)
    max_scalper = float(risk.get("live_max_scalper_confidence", 0.45) or 1)
    min_copy_score = float(risk.get("live_min_copyability_score", 65) or 0)
    min_copy_sample = int(risk.get("live_min_copy_sample", 12) or 0)
    max_jump = float(risk.get("live_max_entry_jump_10s", 0.15) or 1)

    if closed >= 3 and median_hold > 0 and median_hold < min_median:
        return f"Canlı blok: cüzdan çok hızlı satıyor (medyan tutma {median_hold/60:.1f} dk)"
    if short_hold > max_short:
        return f"Canlı blok: kısa süreli satış oranı yüksek (%{short_hold*100:.0f})"
    if sniper_conf > max_sniper:
        return f"Canlı blok: sniper davranışı yüksek ({sniper_conf:.2f})"
    if scalper_conf > max_scalper:
        return f"Canlı blok: scalper davranışı yüksek ({scalper_conf:.2f})"
    if related_tracked > 0:
        return f"Canlı blok: cüzdan bağımsız değil ({related_tracked} takip cüzdanıyla SOL/token transfer bağı)"
    if bool(risk.get("live_require_copy_sample", True)) and copy_sample < min_copy_sample:
        return f"Canlı blok: copy örneklemi yetersiz ({copy_sample}/{min_copy_sample})"
    if copy_sample >= min_copy_sample:
        if copy_score < min_copy_score:
            return f"Canlı blok: copyability düşük ({copy_score:.0f})"
        if bool(risk.get("live_require_positive_copy_pnl_10s", True)) and copy_pnl_10 <= 0:
            return f"Canlı blok: 10sn copy PnL pozitif değil ({copy_pnl_10:+.4f} SOL)"
        if entry_jump_10 > max_jump:
            return f"Canlı blok: 10sn entry jump yüksek (%{entry_jump_10*100:.0f})"
    return None


def _live_token_age_block(token: Token, risk: dict, now_ts: int) -> str | None:
    """Canlı işlemde eski tokenları engelle.

    0.01 SOL copy stratejisinde büyük marj çoğunlukla taze tokenlarda gelir. Aylar
    önce çıkmış tokenlarda lider kâr etse bile follower için gecikme+fee sonrası
    marj zayıf kalır. Yaş verisi DexScreener pair_created_at veya token metrics
    üzerinden okunur; veri yoksa varsayılan olarak bloklamayız.
    """
    if not bool(risk.get("live_fresh_token_only", True)):
        return None
    metrics = token.metrics or {}
    # YAŞ KAYNAĞI (sağlam): taze pump.fun tokeni DexScreener'da olmadığından
    # pair_created_at=0 gelir. 0'ı "epoch 1970" (=56 yıl) sanmak taze token'ı
    # "çok eski" diye REDDETTİRİYORDU (AI'ın launch'ları kaçırmasının ana sebebi).
    # Öncelik: geçerli pair_created_at → on-chain oluşturma → ilk görülme (first_seen).
    created_ts: float | None = None
    pair = metrics.get("pair_created_at")
    try:
        pair_f = float(pair) if pair is not None else 0.0
    except (TypeError, ValueError):
        pair_f = 0.0
    if pair_f > 0:
        created_ts = pair_f / 1000.0 if pair_f > 10_000_000_000 else pair_f
    elif getattr(token, "created_on_chain_at", None):
        created_ts = token.created_on_chain_at.timestamp()
    elif getattr(token, "first_seen", None):
        created_ts = token.first_seen.timestamp()

    if created_ts is None or created_ts <= 0:
        # Yaş gerçekten bilinmiyor: varsayılan olarak ENGELLEME (fresh olabilir).
        return "Canlı blok: token yaşı bilinmiyor" if bool(risk.get("live_require_known_token_age", False)) else None
    age_seconds = max(0.0, float(now_ts) - created_ts)
    min_age = float(risk.get("live_min_token_age_seconds", 0) or 0)
    max_age = float(risk.get("live_max_token_age_minutes", 360) or 0) * 60.0
    if min_age > 0 and age_seconds < min_age:
        return f"Canlı blok: token çok yeni ({age_seconds:.0f} sn < {min_age:.0f} sn)"
    if max_age > 0 and age_seconds > max_age:
        return f"Canlı blok: token eski ({age_seconds/3600:.1f} saat > {max_age/3600:.1f} saat)"
    return None


def get_engine(db: Session, signer=None) -> CopyTradeEngine:
    """Süreç-ömürlü kopya işlem motoru (günlük durum korunur, ayarlar tazelenir).

    Paper sıfırlama (paper_reset token'ı) değiştiyse motoru süreçler arası SIFIRLAR
    — böylece web'den sıfırlama yapılınca worker'daki bellek-içi pozisyonlar da
    temizlenir."""
    global _engine, _engine_reset_token
    cfg = _risk_config(db)
    reset_token = (get_setting(db, "paper_reset") or {}).get("token")
    if _engine is None or reset_token != _engine_reset_token:
        _engine = CopyTradeEngine(cfg, signer=signer)
        # Worker yeniden başladıysa açık pozisyonları + bugünkü harcama/zarar
        # (devre kesici) sayaçlarını DB'den kurtar — yetim pozisyon ve sıfırlanan
        # zarar limiti olmasın. LiveTrade de dahil edilir.
        try:
            stats = _engine.hydrate_from_db(db)
            if stats.get("recovered_positions"):
                logger.info("İşlem motoru DB'den kurtarıldı: %s", stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pozisyon kurtarma başarısız: %s", exc)
        _engine_reset_token = reset_token
    else:
        _engine.cfg = cfg  # günlük harcama/zarar ve paper pozisyonları korunur
        if signer is not None:
            _engine.signer = signer
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


def _to_detected_swap(t: PumpPortalTrade, block_time: int) -> DetectedSwap:
    price = (t.sol_amount / t.token_amount) if t.token_amount else 0.0
    return DetectedSwap(
        signature=t.signature, wallet_address=t.trader, token_mint=t.mint,
        side=t.side, sol_amount=t.sol_amount, token_amount=t.token_amount,
        price_sol=price, fee_sol=0.0, venue=t.pool or "pumpfun",
        block_time=block_time, slot=None, confirmation="confirmed",
    )


def handle_trade_event(
    db: Session,
    trade: PumpPortalTrade,
    *,
    chain: ChainProvider | None = None,
    market: MarketProvider | None = None,
    notifier: TelegramNotifier | None = None,
    signer: PumpPortalTrader | None = None,
    block_time: int | None = None,
) -> dict:
    """Bir PumpPortal trade olayını uçtan uca işler. Sonuç özetini döner.

    `block_time` verilirse (poll yolu) liderin alımından bu yana geçen GERÇEK
    süre (follow_lag) hesaplanır ve geç-giriş koruması uygulanır; canlı WS
    yolunda olay gerçek-zamanlı geldiğinden lag ≈ 0'dır."""
    now = int(datetime.now(timezone.utc).timestamp())
    follow_lag = max(0.0, float(now - block_time)) if block_time else 0.0
    # Canlı alım yolu: throttle KAPALI (düşük gecikme).
    chain = chain or build_chain_provider(throttle=False)
    market = market or build_market_provider()

    # 1) swap'ı kaydet (transfer değil; PumpPortal yalnızca gerçek swap yayınlar)
    swap = _to_detected_swap(trade, now)
    if swap.signature:
        store_swap(db, swap)

    risk_cfg = get_setting(db, "risk")
    strategy_mode = str(risk_cfg.get("strategy_mode", "copy") or "copy").lower()
    strategy_mode = "ai" if strategy_mode == "ai" else "copy"
    is_ai_signal = strategy_mode == "ai" and trade.side == "buy"
    ai_policy = resolve_ai_policy(risk_cfg) if is_ai_signal else {}

    # 2) Strateji kapısı. Modlar birbirini çalıştırmaz:
    #    AI   -> yalnızca token fırsatı sayılan BUY event'leri işlenir; copy sell/buy yok.
    #    Copy -> yalnızca takip edilen cüzdan olayları işlenir; AI sinyali yok.
    if strategy_mode == "ai" and trade.side != "buy":
        return {"action": "ignored", "reason": "AI modu aktif: copy/cüzdan sell olayı işlenmedi", "strategy": "ai"}

    wallet = db.query(Wallet).filter(Wallet.address == trade.trader).first()
    if is_ai_signal:
        if trade.signature:
            exists_paper = db.query(PaperTrade).filter(PaperTrade.source_signature == trade.signature).first()
            exists_live = db.query(LiveTrade).filter(LiveTrade.source_signature == trade.signature).first()
            if exists_paper or exists_live:
                return {"action": "ignored", "reason": "AI sinyali daha önce işlendi"}
        wallet = Wallet(
            address="AI_TRADE", label="AI Trade", status=WalletStatus.tracked.value,
            latest_score=100.0, metrics={}, risk_flags=[], confidence=1.0,
        )
    elif not wallet or wallet.status != WalletStatus.tracked.value:
        return {"action": "ignored", "reason": "cüzdan takipte değil"}

    live_buy = trade.side == "buy" and str(risk_cfg.get("mode", "paper")) == "live"
    if live_buy and is_ai_signal and not bool(risk_cfg.get("ai_live_enabled", False)):
        reason = "AI Trade canlı kilidi kapalı (önce paper doğrula, sonra ai_live_enabled aç)"
        _audit(db, "warning",
               f"AI canlı alım engellendi — {short_addr(trade.mint)}: {reason}",
               {"wallet": trade.trader, "token": trade.mint, "signature": trade.signature, "reason": reason})
        return {"action": "skipped", "reason": reason, "strategy": "ai",
                "wallet": "AI", "token": short_addr(trade.mint), "side": trade.side}

    if live_buy and not is_ai_signal:
        wallet_block = _live_wallet_quality_block(wallet, risk_cfg)
        if wallet_block:
            _audit(db, "warning",
                   f"Canlı alım engellendi — {short_addr(trade.trader)} → "
                   f"{short_addr(trade.mint)}: {wallet_block}",
                   {"wallet": trade.trader, "token": trade.mint,
                    "signature": trade.signature, "reason": wallet_block,
                    "wallet_metrics": wallet.metrics or {}})
            return {"action": "skipped", "reason": wallet_block,
                    "wallet": short_addr(trade.trader), "token": short_addr(trade.mint),
                    "side": trade.side, "wallet_score": wallet.latest_score}

    # 3) tokeni değerlendir (önbellekli, hızlı) — canlı alımda gecikmeyi azaltır.
    # Canlı modda veri çekilemezse fail-closed: gerçek parayla bilinmeyen token
    # alınmaz. Paper modda eski davranış korunur.
    try:
        assessment = assess_token(db, trade.mint, chain, market, settings.token_score_cache_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Token değerlendirilemedi %s: %s", trade.mint, exc)
        if live_buy:
            reason = f"Canlı blok: token değerlendirmesi yapılamadı ({type(exc).__name__})"
            _audit(db, "warning",
                   f"Canlı alım engellendi — {short_addr(trade.trader)} → "
                   f"{short_addr(trade.mint)}: {reason}",
                   {"wallet": trade.trader, "token": trade.mint,
                    "signature": trade.signature, "reason": reason})
            return {"action": "skipped", "reason": reason,
                    "wallet": short_addr(trade.trader), "token": short_addr(trade.mint),
                    "side": trade.side, "wallet_score": wallet.latest_score}
        assessment = TokenAssessment(
            token=get_or_create_token(db, trade.mint), total=0.0, vetoed=False,
            veto_reasons=[f"değerlendirme yapılamadı ({type(exc).__name__})"],
            liquidity_sol=0.0, cached=False,
        )
    token = assessment.token
    token_threshold = float(ai_policy.get("ai_min_token_score", 75) if is_ai_signal else get_setting(db, "thresholds").get("token", 70.0))
    if trade.side == "buy" and (str(risk_cfg.get("mode", "paper")) == "live" or is_ai_signal):
        # COPY TRADE: token yaşı takip/copy stratejisi için sert kapıdır.
        # AI TRADE: bu artık "manuel ayar AI'ı engelledi" değildir; AI'ın kendi
        # fırsat evrenidir. Pump.fun tarafında 100x potansiyel çoğunlukla taze
        # launch penceresindedir. Bu yüzden AI otomatik yönetimde eski tokenı
        # "fırsat evreni dışında" diye ALMADI sayar. Gelişmiş ayarda
        # ai_fresh_universe_enabled kapatılırsa AI her yaşı değerlendirebilir.
        age_risk = risk_cfg
        enforce_age_gate = not is_ai_signal
        if is_ai_signal:
            enforce_age_gate = bool(ai_policy.get("ai_fresh_universe_enabled", True) or ai_policy.get("ai_hard_age_gate", False))
            age_risk = dict(risk_cfg)
            age_risk["live_fresh_token_only"] = True
            age_risk["live_max_token_age_minutes"] = ai_policy.get("ai_max_token_age_minutes", 90)
            age_risk["live_min_token_age_seconds"] = ai_policy.get("ai_min_token_age_seconds", 25)
            age_risk["live_require_known_token_age"] = ai_policy.get("ai_require_known_token_age", True)
        token_age_block = _live_token_age_block(token, age_risk, now) if enforce_age_gate else None
        if token_age_block:
            if is_ai_signal:
                ai_reason = token_age_block.replace("Canlı blok: ", "AI fırsat evreni dışında: ")
                _audit(db, "info",
                       f"AI işlemi ALMADI — {short_addr(trade.mint)}: {ai_reason}",
                       {"wallet": "AI_TRADE", "token": trade.mint,
                        "signature": trade.signature, "reason": ai_reason,
                        "token_metrics": token.metrics or {}, "strategy": "ai",
                        "ai_policy": ai_policy})
                return {"action": "skipped", "reason": ai_reason, "strategy": "ai",
                        "wallet": "AI", "token": short_addr(trade.mint),
                        "side": trade.side, "token_score": assessment.total}
            _audit(db, "warning",
                   f"Canlı alım engellendi — {short_addr(trade.trader)} → "
                   f"{short_addr(trade.mint)}: {token_age_block}",
                   {"wallet": trade.trader, "token": trade.mint,
                    "signature": trade.signature, "reason": token_age_block,
                    "token_metrics": token.metrics or {}})
            return {"action": "skipped", "reason": token_age_block,
                    "wallet": short_addr(trade.trader), "token": short_addr(trade.mint),
                    "side": trade.side, "wallet_score": wallet.latest_score,
                    "token_score": assessment.total}

    # İşlem kapısı politikası: cüzdan alpha; token bir GÜVENLİK filtresidir.
    #   safety   → veto yoksa geç (taze bonding token'lerin düşük puanı engel değil)
    #   balanced → veto yok + puan ≥ 55
    #   score    → veto yok + puan ≥ eşik (klasik katı)
    # VARSAYILAN safety: taze token'ler adil puanlanamadığından kalite eşiği değil
    # GÜVENLİK vetosu uygulanır; asıl sinyal cüzdandır.
    token_gate = str(ai_policy.get("ai_token_gate", "score") if is_ai_signal else risk_cfg.get("token_gate", "safety"))
    if token_gate == "score":
        token_ok = (not assessment.vetoed) and assessment.total >= token_threshold
    elif token_gate == "balanced":
        token_ok = (not assessment.vetoed) and assessment.total >= 55.0
    else:  # safety
        token_ok = not assessment.vetoed

    market_price_sol = swap.price_sol
    liquidity_sol = assessment.liquidity_sol

    # GİRİŞ FİYATI DOĞRULAMA (kritik): liderin zincir-üstü swap'ından çıkarılan fiyat
    # bazı durumlarda hatalı (çok düşük) olabilir → paper motoru "0.01 SOL ile
    # milyarlarca token aldık" sanır (token arzından fazla), güncel fiyatla değer
    # patlar (imkânsız PnL). Token'in CANLI piyasa fiyatı varsa ve lider fiyatı ondan
    # AŞIRI sapıyorsa (parse glitch), piyasa fiyatını kullanırız → gerçekçi miktar +
    # giriş/değerleme tutarlı. Taze token'de piyasa fiyatı yoksa lider fiyatına güveniriz.
    mkt_price = _fresh_market_price(market, trade.mint)
    if mkt_price <= 0:
        mkt_price = float((token.metrics or {}).get("price_sol") or 0.0)
    if mkt_price > 0 and market_price_sol > 0:
        ratio = market_price_sol / mkt_price
        if ratio > 3 or ratio < 0.33:
            logger.warning("Giriş fiyatı düzeltildi %s: swap=%.3g → piyasa=%.3g (oran %.1f)",
                           trade.mint, market_price_sol, mkt_price, ratio)
            market_price_sol = mkt_price
    elif mkt_price > 0 and market_price_sol <= 0:
        market_price_sol = mkt_price
    if is_ai_signal and bool(ai_policy.get("ai_require_price", True)) and market_price_sol <= 0:
        reason = "AI blok: güvenilir giriş fiyatı yok"
        _audit(db, "warning",
               f"AI alım engellendi — {short_addr(trade.mint)}: {reason}",
               {"wallet": trade.trader, "token": trade.mint,
                "signature": trade.signature, "reason": reason})
        return {"action": "skipped", "reason": reason, "strategy": "ai",
                "wallet": "AI", "token": short_addr(trade.mint),
                "side": trade.side, "token_score": assessment.total}
    if live_buy and market_price_sol <= 0:
        reason = "Canlı blok: güvenilir giriş fiyatı yok"
        _audit(db, "warning",
               f"Canlı alım engellendi — {short_addr(trade.trader)} → "
               f"{short_addr(trade.mint)}: {reason}",
               {"wallet": trade.trader, "token": trade.mint,
                "signature": trade.signature, "reason": reason})
        return {"action": "skipped", "reason": reason,
                "wallet": short_addr(trade.trader), "token": short_addr(trade.mint),
                "side": trade.side, "wallet_score": wallet.latest_score,
                "token_score": assessment.total}

    # GLOBAL VERİ FAIL-SAFE: hiçbir piyasa sağlayıcı ayakta değilse (hepsi 'down'),
    # fiyat/likidite bağımsız DOĞRULANAMAZ → canlı/AI YENİ ALIM açma. Satış/çıkış
    # (mirror_sell) bu kapıdan geçmez, her zaman serbesttir. Kayıt yoksa (unknown)
    # engelleme yapılmaz; mevcut per-trade fiyat kontrolleri zaten koruyor.
    if (live_buy or is_ai_signal) and not provider_health.market_data_reliable():
        reason = "Fail-safe: piyasa veri sağlayıcıları down — güvenilir fiyat yok, alım duraklatıldı"
        src = "AI" if is_ai_signal else short_addr(trade.trader)
        _audit(db, "warning",
               f"Alım engellendi (veri fail-safe) — {src} → {short_addr(trade.mint)}: {reason}",
               {"wallet": "AI" if is_ai_signal else trade.trader, "token": trade.mint,
                "signature": trade.signature, "reason": reason,
                "strategy": "ai" if is_ai_signal else "copy",
                "data_status": provider_health.overall_status()})
        return {"action": "skipped", "reason": reason,
                "wallet": src, "token": short_addr(trade.mint),
                "side": trade.side, "wallet_score": wallet.latest_score,
                "token_score": assessment.total}

    if is_ai_signal:
        min_liq = float(ai_policy.get("ai_min_liquidity_sol", 0.0) or 0.0)
        if min_liq > 0 and 0 < liquidity_sol < min_liq:
            reason = f"AI blok: likidite düşük ({liquidity_sol:.2f} SOL < {min_liq:.2f} SOL)"
            _audit(db, "warning",
                   f"AI alım engellendi — {short_addr(trade.mint)}: {reason}",
                   {"wallet": "AI_TRADE", "token": trade.mint, "signature": trade.signature,
                    "reason": reason, "token_score": assessment.total, "ai_policy": ai_policy,
                    "strategy": "ai"})
            return {"action": "skipped", "reason": reason, "strategy": "ai",
                    "wallet": "AI", "token": short_addr(trade.mint), "side": trade.side,
                    "token_score": assessment.total}
        # SAHİPLİK YOĞUNLAŞMASI (yalnız ÖLÇÜLEBİLİYORSA): top-10 cüzdan / insider
        # arzın büyük kısmını tutuyorsa tek dump fiyatı sıfırlar — token-bazlı,
        # cüzdan takibiyle ilgisi yok. Veri yoksa (taze token) engelleme yapılmaz.
        tok_m = (token.metrics or {})
        # metrics'te 0-1 kesir olarak saklanır; limitler yüzde → normalize et.
        def _as_pct(v: float) -> float:
            return v * 100.0 if 0.0 < v <= 1.0 else v
        top10 = _as_pct(float(tok_m.get("top10_pct") or 0.0))
        insider = _as_pct(float(tok_m.get("insider_supply_pct") or 0.0))
        max_top10 = float(ai_policy.get("ai_max_top10_pct", 0.0) or 0.0)
        max_insider = float(ai_policy.get("ai_max_insider_pct", 0.0) or 0.0)
        conc_reason = None
        if max_top10 > 0 and top10 > max_top10:
            conc_reason = f"AI blok: sahiplik yoğun (top10 %{top10:.0f} > %{max_top10:.0f})"
        elif max_insider > 0 and insider > max_insider:
            conc_reason = f"AI blok: insider arzı yüksek (%{insider:.0f} > %{max_insider:.0f})"
        if conc_reason:
            _audit(db, "warning",
                   f"AI alım engellendi — {short_addr(trade.mint)}: {conc_reason}",
                   {"wallet": "AI_TRADE", "token": trade.mint, "signature": trade.signature,
                    "reason": conc_reason, "token_score": assessment.total,
                    "top10_pct": top10, "insider_supply_pct": insider, "strategy": "ai"})
            return {"action": "skipped", "reason": conc_reason, "strategy": "ai",
                    "wallet": "AI", "token": short_addr(trade.mint), "side": trade.side,
                    "token_score": assessment.total}
        # MIGRATION/GRADUATION koruması: bonding curve mezuniyet bölgesindeyse
        # (curve_sol_est yüksek) likidite/slippage oynar ve PumpSwap'a geçişte kör
        # market emri kötü fill verir → yeni AI girişi açma (bekleme moduna geç).
        if (bool(risk_cfg.get("ai_migration_guard_enabled", True))
                and bool(risk_cfg.get("ai_migration_block_entry", True))):
            curve = float(tok_m.get("curve_sol_est") or 0.0)
            mig_floor = float(risk_cfg.get("ai_migration_curve_sol", 75.0) or 0.0)
            if mig_floor > 0 and curve >= mig_floor:
                reason = f"AI blok: migration bölgesi (curve ~{curve:.0f} SOL ≥ {mig_floor:.0f}) — kör giriş yok"
                _audit(db, "warning", f"AI alım engellendi — {short_addr(trade.mint)}: {reason}",
                       {"wallet": "AI_TRADE", "token": trade.mint, "signature": trade.signature,
                        "reason": reason, "token_score": assessment.total, "curve_sol_est": curve,
                        "strategy": "ai"})
                return {"action": "skipped", "reason": reason, "strategy": "ai",
                        "wallet": "AI", "token": short_addr(trade.mint), "side": trade.side,
                        "token_score": assessment.total}
        # ERKEN-DAVRANIŞ (tape) HARD-REJECT: yeterli örnek varsa yapay/riskli
        # girişleri ele. Tek cüzdan pump veya hiç satış olmaması (honeypot şüphesi).
        if bool(risk_cfg.get("ai_tape_gate_enabled", True)):
            tape = tok_m.get("tape") or {}
            n = int(tape.get("trades", 0) or 0)
            if n >= int(risk_cfg.get("ai_tape_min_sample", 8) or 8):
                top = float(tape.get("top_buyer_share", 0.0) or 0.0)
                max_top = float(risk_cfg.get("ai_tape_max_top_buyer_share", 0.7) or 0.7)
                tape_reason = None
                if max_top > 0 and top >= max_top:
                    tape_reason = f"AI blok: tek cüzdan pump (top alıcı %{top*100:.0f} ≥ %{max_top*100:.0f})"
                elif (bool(risk_cfg.get("ai_tape_block_no_sells", True))
                      and int(tape.get("sells", 0) or 0) == 0 and int(tape.get("buys", 0) or 0) >= 6):
                    tape_reason = "AI blok: hiç satış yok (honeypot şüphesi)"
                if tape_reason:
                    _audit(db, "warning", f"AI alım engellendi — {short_addr(trade.mint)}: {tape_reason}",
                           {"wallet": "AI_TRADE", "token": trade.mint, "signature": trade.signature,
                            "reason": tape_reason, "token_score": assessment.total,
                            "tape": tape, "strategy": "ai"})
                    return {"action": "skipped", "reason": tape_reason, "strategy": "ai",
                            "wallet": "AI", "token": short_addr(trade.mint), "side": trade.side,
                            "token_score": assessment.total}

    # AKILLI PARA MUTABAKATI (confluence): bu token'i son pencerede kaç FARKLI takip
    # cüzdanı aldı? 2+ bağımsız kaliteli cüzdan = çok daha güçlü sinyal. İsteğe bağlı
    # kapı: min_confluence > 1 ise yeterli mutabakat yoksa alım yapılmaz.
    from .signals import token_confluence
    min_conf_key = "live_min_confluence" if live_buy else "min_confluence"
    min_conf = int(risk_cfg.get(min_conf_key, risk_cfg.get("min_confluence", 1)) or 1)
    if is_ai_signal:
        min_conf = 1  # AI Trade cüzdan mutabakatına değil token fırsat skoruna bakar.
    conf_window = int(risk_cfg.get("confluence_window_minutes", 30) or 30)
    confluence = token_confluence(db, trade.mint, conf_window) if trade.side == "buy" else 0
    conf_block = None
    if trade.side == "buy" and token_ok and min_conf > 1 and confluence < min_conf:
        token_ok = False
        conf_block = f"mutabakat yetersiz ({confluence}/{min_conf} takip cüzdanı aldı)"

    summary = {
        "wallet": short_addr(trade.trader),
        "token": short_addr(trade.mint),
        "side": trade.side,
        "wallet_score": wallet.latest_score,
        "token_score": assessment.total,
        "token_ok": token_ok,
        "confluence": confluence,
        "cached": assessment.cached,
        "strategy": "ai" if is_ai_signal else "copy",
        "ai_policy": ai_policy if is_ai_signal else None,
    }

    if trade.side == "sell":
        # Hedef satışı yansıt (paper/canlı). Yüzde bilgisini bilemediğimiz için
        # tamamı varsayımıyla yansıtırız (FULL); kısmi oran ileride event'ten gelebilir.
        engine = get_engine(db, signer=signer)
        ctx = _ctx(trade, wallet, assessment.total, assessment.vetoed, market_price_sol, liquidity_sol)
        # Satışta gecikme koruması UYGULANMAZ: lider sattıysa biz de hemen çıkmalıyız.
        try:
            sell_row = engine.on_leader_sell(db, ctx, leader_sell_fraction=1.0)
        except LiveTradingNotConfigured as exc:
            logger.warning("Canlı satış yapılandırılmamış: %s", exc)
            sell_row = None
        summary["action"] = "mirror_sell"
        summary["traded"] = bool(sell_row and getattr(sell_row, "status", "submitted") != "failed")
        if sell_row and engine.cfg.mode == "live":
            _reconcile_live_trade(db, chain, getattr(sell_row, "id", None))
        if sell_row:
            _audit(db, "info",
                   f"Lider SATTI — pozisyon yansıtıldı: {short_addr(trade.trader)} → "
                   f"{short_addr(trade.mint)} ({engine.cfg.mode})",
                   {"wallet": trade.trader, "token": trade.mint, "mode": engine.cfg.mode,
                    "signature": trade.signature, "trade_id": getattr(sell_row, "id", None),
                    "status": getattr(sell_row, "status", None)})
        else:
            _audit(db, "warning",
                   f"Lider SATTI ama yansıtılacak pozisyon bulunamadı/gönderilemedi: "
                   f"{short_addr(trade.trader)} → {short_addr(trade.mint)}",
                   {"wallet": trade.trader, "token": trade.mint, "mode": engine.cfg.mode,
                    "signature": trade.signature})
        return summary

    # ALIM
    if not token_ok:
        summary["action"] = "skipped"
        reason = conf_block or (("güvenlik vetosu: " + ", ".join(assessment.veto_reasons)) if assessment.vetoed
                                else f"token puanı {assessment.total:.0f} < eşik {token_threshold:.0f} ({token_gate})")
        summary["reason"] = reason
        if is_ai_signal:
            _audit(db, "info",
                   f"AI işlemi ALMADI — {short_addr(trade.mint)}: {reason}",
                   {"wallet": "AI_TRADE", "token": trade.mint, "signature": trade.signature,
                    "reason": reason, "token_score": assessment.total,
                    "token_gate": token_gate, "ai_policy": ai_policy, "strategy": "ai"})
        return summary

    # 4) Telegram bildirimi (dedup'lı) — işlemden bağımsız
    notifier = notifier or TelegramNotifier()
    risk_flags = list(assessment.veto_reasons) + list(wallet.risk_flags or [])
    content = AlertContent(
        signature=trade.signature, wallet_address=wallet.address if is_ai_signal else trade.trader,
        wallet_label=wallet.label, wallet_score=wallet.latest_score or 0,
        token_mint=trade.mint, token_name=token.symbol or token.name,
        token_score=assessment.total, amount_token=trade.token_amount,
        sol_value=trade.sol_amount, usd_value=None,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        risk_flags=risk_flags, auto_traded=False,
    )
    alert = notifier.notify(db, content)

    # 5) kopya işlem motoru (paper/canlı) — bağımsız tetiklenir
    engine = get_engine(db, signer=signer)
    decision = None
    if engine.cfg.enabled and engine.cfg.mode != "alerts_only":
        # Giriş miktarı:
        #  - AI avcı (hunter): İLK giriş DAİMA küçük "scout" — körleme büyük girme.
        #    Skor bandına göre boyutlanır; token davranışı sağlıklı kalırsa çıkışlar
        #    ana parayı çıkarıp moonbag taşır (position_manager). (Confirm/scale ekleme
        #    ayrı bir aşamadır; bu sürümde scout girişi uygulanır.)
        #  - Copy: cüzdan-bazlı elle SOL override (varsa) paper sabitini geçersiz kılar.
        if is_ai_signal and bool(risk_cfg.get("ai_hunter_enabled", True)):
            live_mode = str(risk_cfg.get("mode", "paper")) == "live"
            base = float(risk_cfg.get("fixed_sol_amount", 0.05)) if live_mode else float(risk_cfg.get("paper_trade_sol", 0.01))
            sc = float(assessment.total or 0)
            if sc >= 95:
                frac = float(risk_cfg.get("ai_scout_strong_fraction", 0.55) or 0.55)
            elif sc >= float(risk_cfg.get("ai_scout_min_score", 80) or 80):
                frac = float(risk_cfg.get("ai_scout_fraction", 0.35) or 0.35)
            else:
                frac = float(risk_cfg.get("ai_scout_fraction", 0.35) or 0.35) * 0.6
            forced_amount = max(0.0, base * frac)
        elif is_ai_signal:
            forced_amount = None
        else:
            override = get_setting(db, "copy_overrides").get(trade.trader)
            forced_amount = float(override) if override else None
        ctx = _ctx(trade, wallet, assessment.total, assessment.vetoed, market_price_sol, liquidity_sol,
                   forced=forced_amount, follow_lag=follow_lag,
                   strategy="ai" if is_ai_signal else "copy")
        try:
            decision = engine.on_leader_buy(db, ctx)
            if decision and decision.trade_id and engine.cfg.mode == "live":
                _reconcile_live_trade(db, chain, decision.trade_id)
            if alert and decision and decision.allowed:
                alert.auto_traded = True
                db.commit()
        except LiveTradingNotConfigured as exc:
            logger.warning("Canlı işlem yapılandırılmamış: %s", exc)

    summary["action"] = "buy"
    summary["alerted"] = alert is not None
    summary["traded"] = bool(decision and decision.allowed)
    if decision and not decision.allowed:
        summary["trade_blocked"] = decision.reasons
    # Karar logu (Loglar sayfası): işlem yapıldı mı / neden yapılmadı
    if decision and decision.allowed:
        conf_txt = f" · 🔥{confluence} akıllı cüzdan" if confluence >= 2 else ""
        source_label = "AI TRADE" if is_ai_signal else short_addr(trade.trader)
        opened_reason = (
            f"AI uygun gördü: token skoru {assessment.total:.0f}, kapı {token_gate}, "
            f"fiyat {'var' if market_price_sol > 0 else 'yok'}, veto {'yok' if not assessment.vetoed else 'var'}"
            if is_ai_signal else
            f"Copy uygun: takip cüzdanı, token kapısı {token_gate}, veto {'yok' if not assessment.vetoed else 'var'}"
        )
        ai_tape = (token.metrics or {}).get("tape") if is_ai_signal else None
        ai_early_q = None
        if is_ai_signal:
            from .token_tape import early_quality_score
            ai_early_q = early_quality_score(ai_tape)
        _audit(db, "info",
               f"İşlem AÇILDI — {source_label} → {short_addr(trade.mint)} "
               f"({engine.cfg.mode}, {decision.sol_amount:.3f} SOL){conf_txt}",
               {"wallet": wallet.address if is_ai_signal else trade.trader, "token": trade.mint, "wallet_score": wallet.latest_score,
                "token_score": assessment.total, "sol_amount": decision.sol_amount,
                "opened_reason": opened_reason, "reason": opened_reason,
                "entry_price_sol": market_price_sol, "liquidity_sol": liquidity_sol,
                "confluence": confluence, "mode": engine.cfg.mode, "signature": trade.signature,
                "tape": ai_tape, "early_quality": ai_early_q,
                "strategy": "ai" if is_ai_signal else "copy", "ai_policy": ai_policy if is_ai_signal else None})
    else:
        block = decision.reasons if decision else ["işlem motoru kapalı (yalnızca bildirim)"]
        _audit(db, "info",
               f"Bildirim gönderildi, işlem YOK — {short_addr(trade.trader)} → "
               f"{short_addr(trade.mint)}: {', '.join(block)}",
               {"wallet": wallet.address if is_ai_signal else trade.trader, "token": trade.mint, "wallet_score": wallet.latest_score,
                "token_score": assessment.total, "blocked": block, "signature": trade.signature,
                "strategy": "ai" if is_ai_signal else "copy", "ai_policy": ai_policy if is_ai_signal else None})
    return summary


def _ctx(trade: PumpPortalTrade, wallet: Wallet, token_total: float, token_vetoed: bool,
         price_sol: float, liquidity_sol: float, forced: float | None = None,
         follow_lag: float = 0.0, strategy: str = "copy") -> TradeContext:
    return TradeContext(
        wallet_address=wallet.address if strategy == "ai" else trade.trader,
        token_mint=trade.mint,
        wallet_score=wallet.latest_score or 0,
        token_score=token_total,
        token_liquidity_sol=liquidity_sol,
        token_sellable=not token_vetoed,
        follow_lag_seconds=follow_lag,
        market_price_sol=price_sol,
        leader_sol_amount=trade.sol_amount,
        source_signature=trade.signature,
        forced_sol_amount=forced,
        strategy=strategy,
    )

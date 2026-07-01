from app.core.analysis.swap_detection import (
    NormalizedTx, PUMP_FUN_PROGRAM, SYSTEM_PROGRAM, TOKEN_PROGRAM, WSOL_MINT, extract_buyers,
)

BUYER = "Buyer111111111111111111111111111111111111111"
OTHER = "Seller22222222222222222222222222222222222222"
MINT = "Mint1111111111111111111111111111111111111111"


def test_extract_buyers_finds_buyer():
    tx = NormalizedTx(
        signature="s1", block_time=1, slot=1, fee_sol=0.0005,
        programs=[PUMP_FUN_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={BUYER: -1.0, OTHER: 0.99},
        token_deltas={(BUYER, MINT): 5000.0, (OTHER, MINT): -5000.0},
    )
    buyers = extract_buyers(tx)
    assert (BUYER, MINT) in buyers
    assert all(w != OTHER for w, _ in buyers)  # satıcı alıcı değil


def test_extract_buyers_ignores_non_swap():
    # swap venue yok => transfer => alıcı yok
    tx = NormalizedTx(
        signature="s2", block_time=1, slot=1, fee_sol=0.0,
        programs=[SYSTEM_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={BUYER: 0.0},
        token_deltas={(BUYER, MINT): 5000.0},
    )
    assert extract_buyers(tx) == []


def test_extract_buyers_ignores_wsol():
    tx = NormalizedTx(
        signature="s3", block_time=1, slot=1, fee_sol=0.0005,
        programs=[PUMP_FUN_PROGRAM],
        sol_deltas={BUYER: -1.0},
        token_deltas={(BUYER, WSOL_MINT): 1.0},  # WSOL => token alımı sayılmaz
    )
    assert extract_buyers(tx) == []


def test_rate_limiter():
    from app.workers.helius_listener import _RateLimiter
    rl = _RateLimiter(per_min=3)
    assert [rl.allow() for _ in range(5)] == [True, True, True, False, False]


def test_build_ai_trades_from_buy_tx():
    """A1: keşif firehose'undaki bir buy işlemi AI sinyaline (PumpPortalTrade) çevrilir."""
    from app.workers.helius_listener import build_ai_trades
    tx = NormalizedTx(
        signature="aisig1", block_time=1, slot=1, fee_sol=0.0005,
        programs=[PUMP_FUN_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={BUYER: -1.0, OTHER: 0.99},
        token_deltas={(BUYER, MINT): 5000.0, (OTHER, MINT): -5000.0},
    )
    trades = build_ai_trades(tx)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "buy" and t.mint == MINT and t.trader == BUYER
    assert t.signature == "aisig1"
    assert t.raw.get("_strategy") == "ai" and t.raw.get("_source") == "helius-ws"


def test_build_ai_trades_ignores_non_swap():
    from app.workers.helius_listener import build_ai_trades
    tx = NormalizedTx(
        signature="s2", block_time=1, slot=1, fee_sol=0.0,
        programs=[SYSTEM_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={BUYER: 0.0},
        token_deltas={(BUYER, MINT): 5000.0},
    )
    assert build_ai_trades(tx) == []


def test_logs_mention_pumpfun():
    from app.workers.helius_listener import logs_mention_pumpfun
    assert logs_mention_pumpfun([f"Program {PUMP_FUN_PROGRAM} invoke [1]", "Program log: buy"]) is True
    assert logs_mention_pumpfun(["Program SomeOther111 invoke [1]"]) is False
    assert logs_mention_pumpfun([]) is False
    assert logs_mention_pumpfun(None) is False


def test_logs_is_pumpfun_create():
    from app.workers.helius_listener import logs_is_pumpfun_create
    assert logs_is_pumpfun_create([f"Program {PUMP_FUN_PROGRAM} invoke [1]", "Program log: Instruction: Create"]) is True
    assert logs_is_pumpfun_create(["Program log: Instruction: Buy"]) is False
    assert logs_is_pumpfun_create([]) is False


def test_resolve_logs_mode(monkeypatch):
    from app import config as cfg
    import app.workers.helius_listener as hl
    # açık seçim
    monkeypatch.setattr(cfg.settings, "ws_logs_mode", "all", raising=False)
    assert hl._resolve_logs_mode() == "all"
    monkeypatch.setattr(cfg.settings, "ws_logs_mode", "mentions", raising=False)
    assert hl._resolve_logs_mode() == "mentions"
    # auto: Helius anahtarı varsa mentions, yoksa all (Chainstack)
    monkeypatch.setattr(cfg.settings, "ws_logs_mode", "auto", raising=False)
    monkeypatch.setattr(cfg.settings, "helius_api_key", "", raising=False)
    assert hl._resolve_logs_mode() == "all"
    monkeypatch.setattr(cfg.settings, "helius_api_key", "realkey123", raising=False)
    assert hl._resolve_logs_mode() == "mentions"


def test_ai_cooldown_dedups_same_mint():
    from app.workers.helius_listener import HeliusListener
    lis = HeliusListener()
    # cooldown > 0 varsayımıyla: ilk çağrı geçer, hemen ikinci aynı mint geçmez
    first = lis._ai_cooldown_ok(MINT)
    second = lis._ai_cooldown_ok(MINT)
    assert first is True
    assert second is False  # cooldown içinde tekrar yollanmaz


def test_helius_modules_import():
    import app.workers.helius_listener  # noqa: F401
    import app.workers.run_listener  # noqa: F401

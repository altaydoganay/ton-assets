from app.core.analysis.swap_detection import (
    NormalizedTx,
    PUMP_FUN_PROGRAM,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    detect_swap,
    is_transfer,
)

WALLET = "Wa11etAddress1111111111111111111111111111111"
MINT = "MintAddress1111111111111111111111111111111111"


def _buy_tx():
    return NormalizedTx(
        signature="sig_buy",
        block_time=1000,
        slot=1,
        fee_sol=0.0005,
        programs=[PUMP_FUN_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={WALLET: -1.0},
        token_deltas={(WALLET, MINT): 5000.0},
    )


def test_detect_buy():
    swap = detect_swap(_buy_tx(), WALLET)
    assert swap is not None
    assert swap.side == "buy"
    assert swap.token_mint == MINT
    assert round(swap.sol_amount, 4) == 1.0
    assert swap.venue == "pumpfun"


def test_detect_sell():
    tx = NormalizedTx(
        signature="sig_sell", block_time=2000, slot=2, fee_sol=0.0005,
        programs=[PUMP_FUN_PROGRAM],
        sol_deltas={WALLET: 2.0},
        token_deltas={(WALLET, MINT): -5000.0},
    )
    swap = detect_swap(tx, WALLET)
    assert swap is not None
    assert swap.side == "sell"


def test_plain_transfer_is_not_swap():
    # Token geldi ama SOL hareketi yok ve swap programı yok => transfer/airdrop
    tx = NormalizedTx(
        signature="sig_xfer", block_time=3000, slot=3, fee_sol=0.0,
        programs=[SYSTEM_PROGRAM, TOKEN_PROGRAM],
        sol_deltas={WALLET: 0.0},
        token_deltas={(WALLET, MINT): 1000.0},
    )
    assert detect_swap(tx, WALLET) is None
    assert is_transfer(tx, WALLET) is True


def test_swap_program_but_no_sol_move_is_not_swap():
    # Swap programı var ama cüzdanın SOL'u değişmemiş (dust altı) => swap sayma
    tx = NormalizedTx(
        signature="sig_dust", block_time=3000, slot=3, fee_sol=0.0,
        programs=[PUMP_FUN_PROGRAM],
        sol_deltas={WALLET: 0.0},
        token_deltas={(WALLET, MINT): 1000.0},
    )
    assert detect_swap(tx, WALLET) is None


def test_inconsistent_direction_not_swap():
    # SOL ve token aynı yönde artmış => tutarsız
    tx = NormalizedTx(
        signature="sig_bad", block_time=3000, slot=3, fee_sol=0.0,
        programs=[PUMP_FUN_PROGRAM],
        sol_deltas={WALLET: 1.0},
        token_deltas={(WALLET, MINT): 1000.0},
    )
    assert detect_swap(tx, WALLET) is None

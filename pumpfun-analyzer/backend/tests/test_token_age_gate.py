"""Taze token yaş kapısı: pair_created_at=0 (DexScreener'da yok) taze token'ı
'56 yıl eski' sanıp reddetmemeli — bu AI'ın launch'ları kaçırmasının ana bug'ıydı.
"""
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from app.services.live_flow import _live_token_age_block


def _tok(pair_created_at=None, first_seen_min_ago=None, created_on_chain_min_ago=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        metrics={"pair_created_at": pair_created_at},
        first_seen=(now - timedelta(minutes=first_seen_min_ago)) if first_seen_min_ago is not None else None,
        created_on_chain_at=(now - timedelta(minutes=created_on_chain_min_ago)) if created_on_chain_min_ago is not None else None,
    )


RISK = {"live_fresh_token_only": True, "live_min_token_age_seconds": 0,
        "live_max_token_age_minutes": 90, "live_require_known_token_age": False}


def test_fresh_bonding_token_not_rejected_as_old():
    # pair_created_at=0 (DexScreener yok) + 2 dk önce görüldü => TAZE, engellenmemeli
    now_ts = int(time.time())
    tok = _tok(pair_created_at=0, first_seen_min_ago=2)
    assert _live_token_age_block(tok, RISK, now_ts) is None


def test_old_token_via_first_seen_is_rejected():
    # pair yok ama 3 saat önce görülmüş => eski (90 dk üstü) => engellenir
    now_ts = int(time.time())
    tok = _tok(pair_created_at=0, first_seen_min_ago=180)
    res = _live_token_age_block(tok, RISK, now_ts)
    assert res is not None and "eski" in res


def test_valid_pair_created_recent_ok():
    now_ts = int(time.time())
    tok = _tok(pair_created_at=(now_ts - 300) * 1000)  # 5 dk önce (ms)
    assert _live_token_age_block(tok, RISK, now_ts) is None


def test_unknown_age_not_blocked_by_default():
    now_ts = int(time.time())
    tok = _tok(pair_created_at=0)  # first_seen yok, on-chain yok
    assert _live_token_age_block(tok, RISK, now_ts) is None


def test_unknown_age_blocked_when_required():
    now_ts = int(time.time())
    tok = _tok(pair_created_at=0)
    risk = {**RISK, "live_require_known_token_age": True}
    assert "bilinmiyor" in (_live_token_age_block(tok, risk, now_ts) or "")


def test_min_age_gate_still_works():
    now_ts = int(time.time())
    tok = _tok(pair_created_at=0, first_seen_min_ago=0)  # ~şimdi
    risk = {**RISK, "live_min_token_age_seconds": 30}
    res = _live_token_age_block(tok, risk, now_ts)
    assert res is not None and "çok yeni" in res

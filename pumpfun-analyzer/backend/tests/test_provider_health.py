"""Veri sağlayıcı sağlık kaydı + sağlık endpoint entegrasyonu."""
import pytest
from fastapi.testclient import TestClient

from app.adapters.base import MarketProvider, TokenMarketData
from app.adapters.health_tracking import HealthTrackingMarketProvider
from app.main import app
from app.services import provider_health

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_ph():
    provider_health.reset()
    yield
    provider_health.reset()


class _OkMarket(MarketProvider):
    name = "okmkt"
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=True, price_sol=0.001)


class _BadMarket(MarketProvider):
    name = "badmkt"
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=False)


class _RaisingMarket(MarketProvider):
    name = "raisemkt"
    def get_token_market(self, mint):
        raise RuntimeError("network down")


def test_unknown_when_no_calls():
    assert provider_health.overall_status() == "unknown"
    assert provider_health.market_data_reliable() is True  # kayıt yoksa engelleme yok
    assert provider_health.snapshot() == []


def test_ok_provider_records_ok():
    wrapped = HealthTrackingMarketProvider(_OkMarket())
    for _ in range(5):
        d = wrapped.get_token_market("MintAAA")
        assert d.ok is True
    snap = provider_health.snapshot()
    assert len(snap) == 1
    s = snap[0]
    assert s["name"] == "okmkt" and s["kind"] == "market"
    assert s["status"] == "ok" and s["ok"] == 5 and s["fail"] == 0
    assert provider_health.market_data_reliable() is True


def test_ok_false_counts_as_failure_and_goes_down():
    wrapped = HealthTrackingMarketProvider(_BadMarket())
    for _ in range(6):
        wrapped.get_token_market("MintBBB")  # ok=False => fail
    snap = provider_health.snapshot()[0]
    assert snap["fail"] == 6 and snap["consecutive_failures"] == 6
    assert snap["status"] == "down"
    assert provider_health.overall_status() == "down"
    # Tek market sağlayıcı ve o down => fiyat verisi güvenilir DEĞİL
    assert provider_health.market_data_reliable() is False


def test_raising_provider_records_fail_and_reraises():
    wrapped = HealthTrackingMarketProvider(_RaisingMarket())
    with pytest.raises(RuntimeError):
        wrapped.get_token_market("MintCCC")
    snap = provider_health.snapshot()[0]
    assert snap["fail"] == 1
    assert "network down" in (snap["last_error"] or "")


def test_degraded_when_some_failures():
    ok = HealthTrackingMarketProvider(_OkMarket())
    bad = HealthTrackingMarketProvider(_BadMarket())
    # aynı isim değil; degraded tek sağlayıcı penceresinde karışım ister →
    # bunun için ok/fail karışan tek sağlayıcı simüle edelim
    class _Flaky(MarketProvider):
        name = "flaky"
        def __init__(self): self.n = 0
        def get_token_market(self, mint):
            self.n += 1
            return TokenMarketData(mint=mint, source=self.name,
                                   ok=(self.n % 3 != 0))  # ~1/3 başarısız
    fw = HealthTrackingMarketProvider(_Flaky())
    for _ in range(12):
        fw.get_token_market("M")
    snap = [s for s in provider_health.snapshot() if s["name"] == "flaky"][0]
    assert snap["status"] == "degraded"


def test_health_endpoint_exposes_providers():
    # birkaç market çağrısı kaydı üret
    wrapped = HealthTrackingMarketProvider(_OkMarket())
    wrapped.get_token_market("MintZZZ")
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert "data_status" in body and "providers" in body
    assert body["market_data_reliable"] is True
    names = {p["name"] for p in body["providers"]}
    assert "okmkt" in names

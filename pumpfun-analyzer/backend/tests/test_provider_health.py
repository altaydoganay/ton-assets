"""Veri sağlayıcı sağlık kaydı + sağlık endpoint entegrasyonu.

Kritik ayrım: bir market sağlayıcının "veri yok" (taze token, çift bulunamadı)
yanıtı SAĞLIKLIDIR (ok=False ama error=None). Yalnızca gerçek taşıma hatası
(exception ya da data.error dolu) sağlığa 'fail' yazar.
"""
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


class _NoDataMarket(MarketProvider):
    """Taze token: çift yok. ok=False ama error=None => sağlayıcı SAĞLIKLI."""
    name = "nodatamkt"
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=False)


class _ErrorMarket(MarketProvider):
    """Gerçek taşıma hatası: error dolu => sağlığa fail yazar."""
    name = "errmkt"
    def get_token_market(self, mint):
        return TokenMarketData(mint=mint, source=self.name, ok=False, error="HTTP 503")


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


def test_no_data_is_healthy_not_failure():
    """Taze token 'çift yok' yanıtı sağlayıcıyı DOWN göstermemeli."""
    wrapped = HealthTrackingMarketProvider(_NoDataMarket())
    for _ in range(10):
        d = wrapped.get_token_market("FreshMint")
        assert d.ok is False and d.error is None
    snap = provider_health.snapshot()[0]
    assert snap["fail"] == 0 and snap["ok"] == 10
    assert snap["status"] == "ok"
    assert provider_health.market_data_reliable() is True


def test_transport_error_counts_as_failure_and_goes_down():
    wrapped = HealthTrackingMarketProvider(_ErrorMarket())
    for _ in range(6):
        wrapped.get_token_market("MintBBB")  # error dolu => fail
    snap = provider_health.snapshot()[0]
    assert snap["fail"] == 6 and snap["consecutive_failures"] == 6
    assert snap["status"] == "down"
    assert "503" in (snap["last_error"] or "")
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
    class _Flaky(MarketProvider):
        name = "flaky"
        def __init__(self): self.n = 0
        def get_token_market(self, mint):
            self.n += 1
            # ~1/3 çağrı gerçek hata (error dolu), gerisi başarılı
            if self.n % 3 == 0:
                return TokenMarketData(mint=mint, source=self.name, ok=False, error="timeout")
            return TokenMarketData(mint=mint, source=self.name, ok=True, price_sol=0.001)
    fw = HealthTrackingMarketProvider(_Flaky())
    for _ in range(12):
        fw.get_token_market("M")
    snap = [s for s in provider_health.snapshot() if s["name"] == "flaky"][0]
    assert snap["status"] == "degraded"


def test_reliable_when_one_market_up_even_if_another_down():
    up = HealthTrackingMarketProvider(_OkMarket())
    down = HealthTrackingMarketProvider(_ErrorMarket())
    for _ in range(6):
        up.get_token_market("X")
        down.get_token_market("Y")
    # biri down olsa da en az bir market ayakta => veri güvenilir sayılır
    assert provider_health.market_data_reliable() is True


def test_health_endpoint_exposes_providers():
    wrapped = HealthTrackingMarketProvider(_OkMarket())
    wrapped.get_token_market("MintZZZ")
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert "data_status" in body and "providers" in body
    assert body["market_data_reliable"] is True
    names = {p["name"] for p in body["providers"]}
    assert "okmkt" in names

import pytest
from app.adapters.pumpportal import parse_trade_event, PumpPortalTrader, PumpPortalTradeError


def test_parse_buy_event():
    msg = {"txType": "buy", "traderPublicKey": "Wallet1", "mint": "Mint1",
           "solAmount": 1.5, "tokenAmount": 30000, "pool": "pump", "signature": "sig1"}
    t = parse_trade_event(msg)
    assert t is not None
    assert t.side == "buy" and t.trader == "Wallet1" and t.mint == "Mint1"
    assert t.sol_amount == 1.5


def test_parse_non_trade_ignored():
    assert parse_trade_event({"message": "subscribed"}) is None
    assert parse_trade_event({"txType": "create", "mint": "x", "traderPublicKey": "y"}) is None


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.last = None

    def post(self, url, params=None, json=None):
        self.last = {"url": url, "params": params, "json": json}
        return self.resp


def test_submit_buy_returns_signature():
    client = FakeClient(FakeResp(200, {"signature": "txsig123"}))
    trader = PumpPortalTrader(api_key="KEY", client=client)
    sig = trader.submit_buy("Mint1", 0.1, market_price_sol=0.00005, max_slippage=0.1, priority_fee_sol=0.0005)
    assert sig == "txsig123"
    body = client.last["json"]
    assert body["action"] == "buy" and body["mint"] == "Mint1"
    assert body["amount"] == 0.1 and body["denominatedInSol"] == "true"
    assert body["slippage"] == 10
    assert client.last["params"] == {"api-key": "KEY"}


def test_submit_sell_uses_percentage():
    client = FakeClient(FakeResp(200, {"signature": "sellsig"}))
    trader = PumpPortalTrader(api_key="KEY", client=client)
    sig = trader.submit_sell("Mint1", 0.5, market_price_sol=0.0001)
    assert sig == "sellsig"
    assert client.last["json"]["amount"] == "50%"
    assert client.last["json"]["action"] == "sell"


def test_trade_error_on_bad_status():
    client = FakeClient(FakeResp(400, {"error": "insufficient funds"}))
    trader = PumpPortalTrader(api_key="KEY", client=client)
    with pytest.raises(PumpPortalTradeError):
        trader.submit_buy("Mint1", 0.1, 0.0001)


def test_not_configured_without_key():
    trader = PumpPortalTrader(api_key="")
    assert trader.configured is False
    with pytest.raises(PumpPortalTradeError):
        trader.submit_buy("Mint1", 0.1, 0.0001)

import pytest

from app.adapters.rpc import SolanaRpcAdapter, RpcUnavailableError, RateLimitError


def test_rate_limit_retries_same_endpoint():
    calls = {"n": 0}

    def transport(url, payload):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("HTTP 429")
        return {"result": "ok"}

    # min_interval=0 ki test hızlı olsun; rate_limit_retries yeterli
    adapter = SolanaRpcAdapter(endpoints=["https://a"], transport=transport, rate_limit_retries=5)
    # backoff'u sıfırla (testi hızlandır)
    import app.adapters.rpc as rpcmod
    orig_sleep = rpcmod.time.sleep
    rpcmod.time.sleep = lambda *_: None
    try:
        res = adapter.get_token_supply("m")
    finally:
        rpcmod.time.sleep = orig_sleep
    assert res == "ok"
    assert calls["n"] == 3  # 2 kez 429, 3. denemede başarı


def test_rate_limit_gives_up_after_retries():
    def transport(url, payload):
        raise RateLimitError("HTTP 429")

    adapter = SolanaRpcAdapter(endpoints=["https://a"], transport=transport, rate_limit_retries=2)
    import app.adapters.rpc as rpcmod
    orig_sleep = rpcmod.time.sleep
    rpcmod.time.sleep = lambda *_: None
    try:
        with pytest.raises(RpcUnavailableError):
            adapter.get_token_supply("m")
    finally:
        rpcmod.time.sleep = orig_sleep


def test_failover_to_second_endpoint():
    calls = []

    def transport(url, payload):
        calls.append(url)
        if url == "https://bad":
            raise ConnectionError("down")
        return {"jsonrpc": "2.0", "id": 1, "result": ["sig1", "sig2"]}

    adapter = SolanaRpcAdapter(endpoints=["https://bad", "https://good"], transport=transport)
    res = adapter.get_signatures_for_address("addr")
    assert res == ["sig1", "sig2"]
    assert "https://bad" in calls and "https://good" in calls


def test_all_endpoints_fail_raises():
    def transport(url, payload):
        raise ConnectionError("down")

    adapter = SolanaRpcAdapter(endpoints=["https://a", "https://b"], transport=transport)
    with pytest.raises(RpcUnavailableError):
        adapter.get_signatures_for_address("addr")


def test_rpc_error_in_payload_triggers_failover():
    def transport(url, payload):
        if url == "https://a":
            return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "fail"}}
        return {"jsonrpc": "2.0", "id": 1, "result": {"value": 42}}

    adapter = SolanaRpcAdapter(endpoints=["https://a", "https://b"], transport=transport)
    res = adapter.get_token_supply("mint")
    assert res == {"value": 42}


def test_healthy_endpoint_preferred_after_failure():
    state = {"a_fails": True}

    def transport(url, payload):
        if url == "https://a" and state["a_fails"]:
            raise ConnectionError("down")
        return {"result": "ok"}

    adapter = SolanaRpcAdapter(endpoints=["https://a", "https://b"], transport=transport)
    adapter.get_token_supply("m")  # a başarısız, b'ye geçer, b sağlıklı işaretlenir
    # sonraki çağrıda b önce denenmeli
    order = []

    def transport2(url, payload):
        order.append(url)
        return {"result": "ok"}

    adapter.transport = transport2
    adapter.get_token_supply("m2")
    assert order[0] == "https://b"

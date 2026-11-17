import asyncio

import httpx
import pytest

from app.binance_public import BinancePublicDataError, get_binance_public_json


def test_public_rest_fails_over_from_server_error_to_market_data_host():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(503, json={"msg": "temporarily unavailable"})
        return httpx.Response(200, json={"symbols": ["BTCUSDT"]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            payload, source = await get_binance_public_json(
                client, "/api/v3/exchangeInfo",
                base_urls=("https://primary.test", "https://mirror.test"),
            )
        return payload, source

    payload, source = asyncio.run(run())
    assert payload == {"symbols": ["BTCUSDT"]}
    assert source == "https://mirror.test"
    assert requests == ["primary.test", "mirror.test"]


def test_public_rest_fails_over_after_transport_error():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        if request.url.host == "primary.test":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_binance_public_json(
                client, "/api/v3/ping",
                base_urls=("https://primary.test", "https://mirror.test"),
            )

    payload, source = asyncio.run(run())
    assert payload == {"ok": True}
    assert source == "https://mirror.test"
    assert requests == ["primary.test", "mirror.test"]


def test_public_rest_does_not_retry_invalid_symbol_client_error():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BinancePublicDataError, match="Invalid symbol") as exc:
                await get_binance_public_json(
                    client, "/api/v3/aggTrades",
                    {"symbol": "NOTREAL"},
                    base_urls=("https://primary.test", "https://mirror.test"),
                )
        return exc.value

    error = asyncio.run(run())
    assert error.status_code == 400
    assert requests == ["primary.test"]


def test_public_rest_stops_immediately_on_rate_limit_and_preserves_retry_after():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        return httpx.Response(
            429, json={"code": -1003, "msg": "Too many requests"},
            headers={"Retry-After": "3"},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BinancePublicDataError, match="Retry-After=3") as exc:
                await get_binance_public_json(
                    client, "/api/v3/exchangeInfo",
                    base_urls=("https://primary.test", "https://mirror.test"),
                )
        return exc.value

    error = asyncio.run(run())
    assert error.status_code == 429
    assert error.retry_after == "3"
    assert requests == ["primary.test"]


def test_public_rest_reports_all_hosts_when_every_endpoint_fails():
    def handler(request):
        return httpx.Response(502, json={"msg": "bad gateway"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BinancePublicDataError) as exc:
                await get_binance_public_json(
                    client, "/api/v3/exchangeInfo",
                    base_urls=("https://primary.test", "https://mirror.test"),
                )
        return exc.value

    error = asyncio.run(run())
    assert "primary.test: HTTP 502" in str(error)
    assert "mirror.test: HTTP 502" in str(error)


def test_public_rest_rejects_non_public_routes():
    async def run():
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError, match="public Spot"):
                await get_binance_public_json(client, "/api/v3/../account")

    asyncio.run(run())


def test_public_request_limit_is_safe_across_separate_event_loops():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await asyncio.gather(*[
                get_binance_public_json(
                    client, "/api/v3/ping", base_urls=("https://mirror.test",)
                )
                for _ in range(8)
            ])
        assert len(results) == 8
        assert all(payload == {"ok": True} for payload, _source in results)

    asyncio.run(run())
    asyncio.run(run())


def test_public_rest_remembers_last_successful_host_within_event_loop():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(503, json={"msg": "primary unavailable"})
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await get_binance_public_json(
                client, "/api/v3/ping",
                base_urls=("https://primary.test", "https://mirror.test"),
            )
            second = await get_binance_public_json(
                client, "/api/v3/ping",
                base_urls=("https://primary.test", "https://mirror.test"),
            )
        return first, second

    first, second = asyncio.run(run())
    assert first == ({"ok": True}, "https://mirror.test")
    assert second == ({"ok": True}, "https://mirror.test")
    assert requests == ["primary.test", "mirror.test", "mirror.test"]


@pytest.mark.parametrize(
    ("status", "message"),
    [(403, "WAF security block"), (451, "Region restricted")],
)
def test_public_rest_stops_on_waf_or_geo_restriction(status, message):
    requests = []

    def handler(request):
        requests.append(request.url.host)
        return httpx.Response(status, json={"msg": message})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BinancePublicDataError, match=message):
                await get_binance_public_json(
                    client, "/api/v3/exchangeInfo",
                    base_urls=("https://primary.test", "https://mirror.test"),
                )

    asyncio.run(run())
    assert requests == ["primary.test"]

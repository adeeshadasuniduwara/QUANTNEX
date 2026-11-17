from datetime import datetime, timezone, timedelta
import asyncio

import httpx
import pytest

from app.binance_order_flow_feed import (
    BinanceOrderFlowFeedError,
    fetch_spot_order_flow,
)

NOW = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)


def _client():
    stamp = int((NOW - timedelta(seconds=2)).timestamp() * 1000)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/aggTrades"):
            return httpx.Response(200, json=[
                {"a": 1, "p": "100", "q": "2", "T": stamp, "m": False},
                {"a": 2, "p": "100.1", "q": "1", "T": stamp + 500, "m": True},
            ])
        return httpx.Response(200, json={
            "lastUpdateId": 123456,
            "bids": [["100", "3"], ["99.9", "2"]],
            "asks": [["100.1", "2"], ["100.2", "1"]],
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_public_rest_collector_returns_provenance_and_snapshot_only_depth():
    async def run():
        async with _client() as client:
            result = await fetch_spot_order_flow(
                client, "BTCUSDT", tick_size="0.1", now=NOW
            )
        assert result["symbol"] == "BTCUSDT"
        assert result["market_type"] == "BINANCE_SPOT"
        assert result["buy_volume"] == 2
        assert result["sell_volume"] == 1
        assert result["delta"] == 1
        assert result["depth_snapshot_update_id"] == 123456
        assert result["depth_is_continuous"] is False
        assert result["feed_mode"] == "PUBLIC_REST_SNAPSHOT"
        assert result["data_provenance"]["candle_volume_used"] is False

    asyncio.run(run())


def test_public_rest_collector_rejects_invalid_symbol_before_network():
    async def run():
        async with _client() as client:
            with pytest.raises(BinanceOrderFlowFeedError, match="symbol"):
                await fetch_spot_order_flow(client, "BTC/USDT", tick_size="0.1", now=NOW)

    asyncio.run(run())


def test_public_rest_collector_fails_closed_for_stale_trades():
    async def run():
        async with _client() as client:
            with pytest.raises(BinanceOrderFlowFeedError, match="stale"):
                await fetch_spot_order_flow(
                    client, "BTCUSDT", tick_size="0.1",
                    now=NOW + timedelta(seconds=30), max_trade_age_seconds=15,
                )

    asyncio.run(run())

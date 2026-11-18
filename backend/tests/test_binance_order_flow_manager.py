import asyncio

import pytest

from app.binance_order_flow_manager import (
    BinanceSpotOrderFlowManager,
    BinanceSpotOrderFlowManagerError,
)


class FakeStream:
    instances = []

    def __init__(self, symbol, tick_size, *, max_trade_age_seconds, max_depth_age_seconds):
        self.symbol = symbol
        self.tick_size = tick_size
        self.max_trade_age_seconds = max_trade_age_seconds
        self.max_depth_age_seconds = max_depth_age_seconds
        self.status = "STOPPED"
        self.ready = True
        self.run_count = 0
        self.__class__.instances.append(self)

    def snapshot(self):
        return {
            "symbol": self.symbol,
            "market_type": "BINANCE_SPOT",
            "status": self.status,
            "signal_ready": self.ready and self.status == "LIVE",
            "order_flow": {"market_type": "BINANCE_SPOT"} if self.ready and self.status == "LIVE" else None,
            "last_error": None,
        }

    async def run(self, _client, stop_event, on_update):
        self.run_count += 1
        self.status = "LIVE" if self.ready else "BOOTSTRAPPING"
        await on_update(self.snapshot())
        await stop_event.wait()
        self.status = "STOPPED"


def setup_function():
    FakeStream.instances.clear()


def test_manager_starts_and_reuses_one_stream_per_symbol():
    async def run():
        manager = BinanceSpotOrderFlowManager(max_streams=2, stream_factory=FakeStream)
        first = await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)
        second = await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)

        assert first["signal_ready"] is True
        assert second["signal_ready"] is True
        assert second["manager"]["active_streams"] == 1
        assert len(FakeStream.instances) == 1
        assert FakeStream.instances[0].run_count == 1

        await manager.stop()
        assert FakeStream.instances[0].status == "STOPPED"
        assert manager.active_stream_count == 0

    asyncio.run(run())


def test_manager_evicts_least_recently_requested_stream_at_capacity():
    async def run():
        manager = BinanceSpotOrderFlowManager(max_streams=1, stream_factory=FakeStream)
        btc = await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)
        eth = await manager.get_snapshot("ETHUSDT", "0.01", wait_seconds=0.1)

        assert btc["signal_ready"] is True
        assert eth["signal_ready"] is True
        assert len(FakeStream.instances) == 2
        assert FakeStream.instances[0].status == "STOPPED"
        assert FakeStream.instances[1].symbol == "ETHUSDT"
        assert manager.active_stream_count == 1

        await manager.stop()

    asyncio.run(run())


def test_manager_returns_explicit_not_ready_state_without_fabricating_order_flow():
    async def run():
        def not_ready_factory(*args, **kwargs):
            stream = FakeStream(*args, **kwargs)
            stream.ready = False
            return stream

        manager = BinanceSpotOrderFlowManager(max_streams=1, stream_factory=not_ready_factory)
        result = await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.01)

        assert result["status"] == "BOOTSTRAPPING"
        assert result["signal_ready"] is False
        assert result["order_flow"] is None
        await manager.stop()

    asyncio.run(run())


@pytest.mark.parametrize("tick_size", ["0", "-0.01", "NaN", "Infinity", "not-a-tick"])
def test_manager_rejects_invalid_tick_size_before_starting_client(tick_size):
    async def run():
        manager = BinanceSpotOrderFlowManager(stream_factory=FakeStream)
        with pytest.raises(BinanceSpotOrderFlowManagerError, match="tick size"):
            await manager.get_snapshot("BTCUSDT", tick_size)
        assert manager._client is None

    asyncio.run(run())


def test_manager_restarts_symbol_stream_when_exchange_tick_size_changes():
    async def run():
        manager = BinanceSpotOrderFlowManager(max_streams=2, stream_factory=FakeStream)
        await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)
        await manager.get_snapshot("BTCUSDT", "0.1", wait_seconds=0.1)

        assert len(FakeStream.instances) == 2
        assert FakeStream.instances[0].status == "STOPPED"
        assert FakeStream.instances[1].tick_size == "0.1"
        await manager.stop()

    asyncio.run(run())

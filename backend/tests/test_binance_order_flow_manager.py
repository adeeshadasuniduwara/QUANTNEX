import asyncio

import pytest

from app import binance_order_flow_manager as manager_module
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


def test_manager_persists_ready_stream_snapshots_off_the_websocket_callback(monkeypatch):
    async def run():
        manager = BinanceSpotOrderFlowManager(max_streams=1, stream_factory=FakeStream)
        captures = []
        monkeypatch.setattr(manager_module, "is_recordable_order_flow_snapshot", lambda _snapshot: True)
        monkeypatch.setattr(manager_module, "_seconds_until_next_utc_minute", lambda _stamp: 1.0)
        monkeypatch.setattr(
            manager_module,
            "_snapshot_stays_fresh_until_next_minute",
            lambda *_args, **_kwargs: True,
        )
        monkeypatch.setattr(
            manager,
            "_persist_snapshot",
            lambda snapshot, captured_at, prune_before: captures.append((snapshot, captured_at, prune_before)),
        )

        result = await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)
        assert result["signal_ready"] is True
        assert result["manager"]["capture"]["enabled"] is True
        await manager.stop()

        assert len(captures) == 1
        assert captures[0][0]["symbol"] == "BTCUSDT"
        assert captures[0][1].tzinfo is not None

    asyncio.run(run())



def test_capture_window_aligns_samples_before_utc_minute_decisions():
    from datetime import datetime, timezone

    before_window = datetime(2026, 11, 20, 12, 34, 57, 999999, tzinfo=timezone.utc)
    window_open = datetime(2026, 11, 20, 12, 34, 58, tzinfo=timezone.utc)
    near_boundary = datetime(2026, 11, 20, 12, 34, 59, 500000, tzinfo=timezone.utc)

    assert manager_module._seconds_until_next_utc_minute(before_window) is None
    assert manager_module._seconds_until_next_utc_minute(window_open) == pytest.approx(2.0)
    assert manager_module._seconds_until_next_utc_minute(near_boundary) == pytest.approx(0.5)
    assert manager_module._seconds_until_next_utc_minute(
        datetime(2026, 11, 20, 12, 34, 59)
    ) is None


@pytest.mark.parametrize(
    ("trade_age", "depth_age", "remaining", "expected"),
    [
        (13.0, 3.0, 2.0, True),
        (13.01, 3.0, 2.0, False),
        (13.0, 3.01, 2.0, False),
        (14.0, 4.0, 2.0, False),
        (-0.1, 1.0, 1.0, False),
        (float("nan"), 1.0, 1.0, False),
        (1.0, float("inf"), 1.0, False),
    ],
)
def test_capture_rejects_sources_that_will_be_stale_at_next_minute(
    trade_age, depth_age, remaining, expected
):
    snapshot = {
        "order_flow": {"trade_data_age_seconds": trade_age},
        "depth_age_seconds": depth_age,
    }
    assert manager_module._snapshot_stays_fresh_until_next_minute(
        snapshot,
        remaining,
        max_trade_age_seconds=15.0,
        max_depth_age_seconds=5.0,
    ) is expected


def test_manager_skips_capture_outside_utc_boundary_alignment_window(monkeypatch):
    async def run():
        manager = BinanceSpotOrderFlowManager(max_streams=1, stream_factory=FakeStream)
        captures = []
        monkeypatch.setattr(manager_module, "is_recordable_order_flow_snapshot", lambda _snapshot: True)
        monkeypatch.setattr(manager_module, "_seconds_until_next_utc_minute", lambda _stamp: None)
        monkeypatch.setattr(
            manager,
            "_persist_snapshot",
            lambda snapshot, captured_at, prune_before: captures.append(snapshot),
        )

        await manager.get_snapshot("BTCUSDT", "0.01", wait_seconds=0.1)
        await manager.stop()
        assert captures == []

    asyncio.run(run())

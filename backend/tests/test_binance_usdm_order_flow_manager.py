import asyncio
from collections import deque
import pytest
import time
from app.binance_usdm_order_flow_manager import BinanceUsdmOrderFlowManager
from app.binance_usdm_order_flow_stream import UsdmStreamError

class FakeStream:
    def __init__(self):
        self.capture_events=deque()

def test_usdm_manager_enforces_bounded_unique_capture_symbols():
    with pytest.raises(ValueError):
        BinanceUsdmOrderFlowManager(symbols=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT"])
    manager=BinanceUsdmOrderFlowManager(symbols=["BTCUSDT","ETHUSDT"])
    with pytest.raises(UsdmStreamError):
        manager.get_snapshot("SOLUSDT")

def test_usdm_manager_batches_raw_event_persistence(monkeypatch):
    async def run():
        manager=BinanceUsdmOrderFlowManager(symbols=["BTCUSDT"])
        stream=FakeStream()
        manager.streams["BTCUSDT"]=stream
        real_monotonic=time.monotonic()
        manager._last_flush["BTCUSDT"]=real_monotonic
        monkeypatch.setattr("app.binance_usdm_order_flow_manager.time.monotonic",lambda:real_monotonic+0.1)
        persisted=[]
        monkeypatch.setattr(manager,"_persist",lambda batch:persisted.extend(batch) or {"stored":len(batch)})
        stream.capture_events.append({"event_key":"small"})
        await manager._on_update("BTCUSDT",{"status":"LIVE"})
        assert not persisted
        for index in range(64):
            stream.capture_events.append({"event_key":str(index)})
        await manager._on_update("BTCUSDT",{"status":"LIVE"})
        await asyncio.gather(*list(manager._persist_tasks))
        await asyncio.sleep(0)
        assert len(persisted)==65
        assert manager.persisted_events==65
    asyncio.run(run())

def test_usdm_manager_sync_persistence_uses_recorder_and_closes_session(monkeypatch):
    class FakeDB:
        closed=False
        def close(self): self.closed=True
    db=FakeDB()
    manager=BinanceUsdmOrderFlowManager(symbols=["BTCUSDT"])
    monkeypatch.setattr("app.binance_usdm_order_flow_manager.SessionLocal",lambda:db)
    monkeypatch.setattr("app.binance_usdm_order_flow_manager.record_usdm_market_events",
        lambda active,events:{"stored":len(events),"duplicates":0})
    assert manager._persist([{"event_key":"1"}])["stored"]==1
    assert db.closed is True

"""Bounded lifecycle manager for read-only USDⓈ-M Futures Order Flow streams."""
from __future__ import annotations
import asyncio, threading, time
from datetime import datetime, timedelta, timezone
import httpx
from .binance_usdm_order_flow_stream import BinanceUsdmOrderFlowStream, UsdmStreamError
from .database import SessionLocal
from .order_flow_usdm_recorder import record_usdm_market_events

DEFAULT_USDM_SYMBOLS = ("BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT")
MAX_USDM_STREAMS = 5

class BinanceUsdmOrderFlowManager:
    def __init__(self, *, symbols=DEFAULT_USDM_SYMBOLS, max_streams=MAX_USDM_STREAMS,
                 stream_factory=BinanceUsdmOrderFlowStream):
        normalized=[]
        for value in symbols:
            symbol=str(value or "").strip().upper()
            if symbol.isalnum() and 5 <= len(symbol) <= 25 and symbol not in normalized:
                normalized.append(symbol)
        if not normalized or len(normalized)>max_streams or max_streams>MAX_USDM_STREAMS:
            raise ValueError("USDⓈ-M Futures stream list must contain 1–5 valid unique symbols.")
        self.symbols=tuple(normalized); self.max_streams=max_streams; self.stream_factory=stream_factory
        self.streams={}; self.tasks={}; self.stop_events={}; self.snapshots={}
        self.client=None; self.closed=False; self._lock=asyncio.Lock()
        self._persist_tasks=set(); self.last_persist_error=None; self.last_persist_at=None
        self.persisted_events=0; self._prune_lock=threading.Lock(); self._last_prune=0.0
        self._last_flush: dict[str, float] = {}

    async def start(self):
        async with self._lock:
            if self.client is None or self.client.is_closed:
                self.client=httpx.AsyncClient(timeout=httpx.Timeout(8.0,connect=3.0),
                    limits=httpx.Limits(max_connections=self.max_streams*2,max_keepalive_connections=self.max_streams))
            self.closed=False
            for symbol in self.symbols:
                if symbol in self.tasks and not self.tasks[symbol].done(): continue
                stream=self.stream_factory(symbol)
                stop=asyncio.Event()
                self.streams[symbol]=stream; self.stop_events[symbol]=stop
                task=asyncio.create_task(stream.run(self.client,stop,
                    on_update=lambda snap,s=symbol:self._on_update(s,snap)),
                    name=f"quantnex-usdm-orderflow-{symbol.lower()}")
                self.tasks[symbol]=task

    def _persist(self, events):
        db=SessionLocal()
        try:
            return record_usdm_market_events(db,events)
        finally: db.close()

    async def _on_update(self,symbol,snapshot):
        self.snapshots[symbol]=snapshot
        stream=self.streams.get(symbol)
        if stream is None: return
        now=time.monotonic()
        flush_due=(len(stream.capture_events)>=64 or symbol not in self._last_flush
                   or now-self._last_flush.get(symbol,0.0)>=1.0
                   or snapshot.get("status") in {"RECONNECTING","STOPPED"})
        if not flush_due: return
        batch=[]
        while stream.capture_events and len(batch)<256: batch.append(stream.capture_events.popleft())
        if batch:
            self._last_flush[symbol]=now
            task=asyncio.create_task(asyncio.to_thread(self._persist,batch),
                name=f"quantnex-usdm-persist-{symbol.lower()}")
            self._persist_tasks.add(task)
            def finished(done):
                self._persist_tasks.discard(done)
                if done.cancelled(): return
                try:
                    result=done.result(); self.persisted_events+=int(result.get("stored",0))
                    self.last_persist_at=datetime.now(timezone.utc).isoformat(); self.last_persist_error=None
                except Exception as exc:
                    self.last_persist_error=f"{type(exc).__name__}: {exc}"
                    active=self.streams.get(symbol)
                    if active is not None:
                        for event in reversed(batch):
                            active.capture_events.appendleft(event)
            task.add_done_callback(finished)

    async def stop(self):
        async with self._lock:
            self.closed=True
            for event in self.stop_events.values(): event.set()
            tasks=list(self.tasks.values()); client=self.client
            self.tasks={}; self.streams={}; self.stop_events={}; self.snapshots={}; self.client=None
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        if self._persist_tasks: await asyncio.gather(*list(self._persist_tasks),return_exceptions=True)
        if client and not client.is_closed: await client.aclose()

    def get_snapshot(self,symbol):
        normalized=str(symbol or "").strip().upper()
        if normalized not in self.symbols:
            raise UsdmStreamError("This symbol is not in the bounded USDⓈ-M Futures capture set.")
        stream=self.streams.get(normalized)
        if stream is None: return {"market_type":"BINANCE_USDM_FUTURES","symbol":normalized,"status":"STARTING","sequence_valid":False,"depth_ready":False}
        return stream.snapshot()

    def status(self):
        return {"market_type":"BINANCE_USDM_FUTURES","enabled":self.client is not None and not self.closed,
            "configured_symbols":list(self.symbols),"max_streams":self.max_streams,
            "active_streams":sum(not t.done() for t in self.tasks.values()),
            "streams":{s:self.get_snapshot(s) for s in self.symbols},
            "persisted_events":self.persisted_events,"last_persist_at":self.last_persist_at,
            "last_persist_error":self.last_persist_error,
            "retention_days":7,"coverage":"OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE",
            "execution_enabled":False}

_manager=BinanceUsdmOrderFlowManager()
async def start_binance_usdm_order_flow_manager(): await _manager.start()
async def stop_binance_usdm_order_flow_manager(): await _manager.stop()
def get_binance_usdm_order_flow_manager(): return _manager

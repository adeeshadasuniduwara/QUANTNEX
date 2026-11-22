"""Read-only Binance USDⓈ-M Futures aggTrade + diff-depth stream.

Depth is published only after a REST snapshot bridge and a continuous Futures
pu chain. Any gap, malformed event or queue overflow invalidates the book and
forces reconnect/resnapshot. This module never places orders.
"""
from __future__ import annotations
import asyncio, json, math, time, uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable
import httpx
from websockets.asyncio.client import connect
from .binance_usdm_order_flow import (
    MARKET_TYPE, FuturesOrderFlowError, normalize_usdm_agg_trade,
    normalize_usdm_depth_update,
)

WS_BASE = "wss://fstream.binance.com/stream"
REST_DEPTH = "https://fapi.binance.com/fapi/v1/depth"
MAX_BUFFERED = 4096

class UsdmStreamError(RuntimeError):
    pass

class BinanceUsdmOrderFlowStream:
    def __init__(self, symbol: str, *, websocket_factory=connect, max_buffered_events=MAX_BUFFERED,
                 reconnect_initial_seconds=1.0, reconnect_max_seconds=30.0):
        self.symbol = str(symbol or "").strip().upper()
        if not self.symbol.isalnum() or not 5 <= len(self.symbol) <= 25:
            raise UsdmStreamError("Invalid USDⓈ-M Futures symbol.")
        if isinstance(max_buffered_events, bool) or not isinstance(max_buffered_events, int) or max_buffered_events < 100:
            raise UsdmStreamError("Futures event buffer must be at least 100.")
        if not 0 < reconnect_initial_seconds <= reconnect_max_seconds:
            raise UsdmStreamError("Invalid reconnect backoff bounds.")
        self.websocket_factory = websocket_factory
        self.max_buffered_events = max_buffered_events
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.session_id = uuid.uuid4().hex
        self.capture_events = deque()
        self.recent_trades: deque[dict[str, Any]] = deque(maxlen=5000)
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id = None
        self.sequence_valid = False
        self.last_trade = None
        self.last_trade_at = None
        self.last_depth_at = None
        self.last_message_at = None
        self.status = "STOPPED"
        self.last_error = None
        self.gap_count = 0
        self.trade_count = 0
        self.dropped_events = 0
        self.stream_url = f"{WS_BASE}?streams={self.symbol.lower()}@aggTrade/{self.symbol.lower()}@depth@100ms"

    def _queue(self, event):
        if len(self.capture_events) >= self.max_buffered_events:
            self.dropped_events += 1
            self.sequence_valid = False
            raise UsdmStreamError("Futures raw-event queue overflow; capture continuity lost.")
        self.capture_events.append(event)

    async def _receive_to_queue(self, websocket, queue, stop_event):
        while not stop_event.is_set():
            raw = await websocket.recv()
            try:
                msg = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                raise UsdmStreamError("Invalid Futures WebSocket JSON.") from exc
            data = msg.get("data") if isinstance(msg, dict) else None
            if not isinstance(data, dict) or str(data.get("s") or "").upper() != self.symbol:
                raise UsdmStreamError("Futures stream symbol mismatch.")
            stream_name = str(msg.get("stream") or "").lower()
            if stream_name and not stream_name.startswith(self.symbol.lower() + "@"):
                raise UsdmStreamError("Futures combined-stream name mismatch.")
            kind = data.get("e")
            if kind not in {"aggTrade", "depthUpdate"}:
                continue
            if queue.full():
                raise UsdmStreamError("Futures bootstrap queue overflow.")
            await queue.put((kind, data, int(time.time() * 1000)))

    def _apply_depth(self, event):
        if event["market_type"] != MARKET_TYPE or event["symbol"] != self.symbol:
            raise UsdmStreamError("Cross-market or cross-symbol Futures depth event rejected.")
        p = event["payload"]
        if self.last_update_id is None:
            if not (p["U"] <= self.snapshot_update_id <= p["u"]):
                if p["u"] <= self.snapshot_update_id:
                    return False
                raise UsdmStreamError("Futures depth event failed to bridge REST snapshot.")
        else:
            if p["pu"] != self.last_update_id or p["u"] <= self.last_update_id:
                self.sequence_valid = False
                self.gap_count += 1
                raise UsdmStreamError("Futures pu sequence gap; invalidate and resnapshot.")
        for price, qty in p["b"]:
            px, q = float(price), float(qty)
            if q == 0: self.bids.pop(px, None)
            else: self.bids[px] = q
        for price, qty in p["a"]:
            px, q = float(price), float(qty)
            if q == 0: self.asks.pop(px, None)
            else: self.asks[px] = q
        self.last_update_id = p["u"]
        self.sequence_valid = True
        self.last_depth_at = datetime.fromtimestamp(event["event_time_ms"] / 1000, tz=timezone.utc)
        self.last_message_at = datetime.now(timezone.utc)
        self._queue({**event, "source":"WEBSOCKET", "stream_session_id":self.session_id})
        return True

    def _apply_trade(self, data, received_ms):
        event = normalize_usdm_agg_trade(self.symbol, data, received_at_ms=received_ms)
        event.update({"source":"WEBSOCKET", "stream_session_id":self.session_id})
        self.last_trade = {"price":event["payload"]["p"],"quantity":event["payload"]["q"],
                           "buyer_is_maker":event["payload"]["m"],"event_time_ms":event["event_time_ms"]}
        self.last_trade_at = datetime.fromtimestamp(event["event_time_ms"] / 1000, tz=timezone.utc)
        self.last_message_at = datetime.now(timezone.utc)
        self.recent_trades.append({
            "event_time_ms": event["event_time_ms"],
            "quantity": float(event["payload"]["q"]),
            "buyer_is_maker": event["payload"]["m"],
        })
        self.trade_count += 1
        self._queue(event)

    async def _bootstrap(self, websocket, client, stop_event):
        queue = asyncio.Queue(maxsize=2048)
        receiver = asyncio.create_task(self._receive_to_queue(websocket, queue, stop_event))
        try:
            response = await client.get(REST_DEPTH, params={"symbol":self.symbol,"limit":1000})
            response.raise_for_status()
            snapshot = response.json()
            if (not isinstance(snapshot, dict) or isinstance(snapshot.get("lastUpdateId"), bool)
                    or not isinstance(snapshot.get("lastUpdateId"), int) or snapshot["lastUpdateId"] < 0):
                raise UsdmStreamError("Invalid USDⓈ-M Futures REST depth snapshot.")
            def snapshot_side(rows):
                if not isinstance(rows, list):
                    raise UsdmStreamError("Futures REST snapshot side must be an array.")
                result = {}
                for level in rows:
                    if not isinstance(level, (list, tuple)) or len(level) < 2:
                        raise UsdmStreamError("Malformed Futures REST snapshot price level.")
                    try:
                        price, quantity = float(level[0]), float(level[1])
                    except (TypeError, ValueError, OverflowError):
                        raise UsdmStreamError("Non-numeric Futures REST snapshot level.") from None
                    if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0:
                        raise UsdmStreamError("Out-of-range Futures REST snapshot level.")
                    if quantity > 0:
                        result[price] = quantity
                return result
            self.snapshot_update_id = snapshot["lastUpdateId"]
            self.last_update_id = None
            self.bids = snapshot_side(snapshot.get("bids"))
            self.asks = snapshot_side(snapshot.get("asks"))
            deadline = time.monotonic() + 10
            while not stop_event.is_set() and not self.sequence_valid:
                remaining = deadline-time.monotonic()
                if remaining <= 0: raise UsdmStreamError("Timed out waiting for Futures snapshot bridge.")
                try: kind,data,received_ms = await asyncio.wait_for(queue.get(), timeout=min(1.0,remaining))
                except asyncio.TimeoutError: continue
                if kind == "aggTrade":
                    self._apply_trade(data, received_ms)
                else:
                    normalized = normalize_usdm_depth_update(self.symbol,data,received_at_ms=received_ms)
                    self._apply_depth(normalized)
            if not self.sequence_valid:
                raise UsdmStreamError("Futures snapshot bridge was not validated.")
            return receiver, queue
        except Exception:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            raise

    def snapshot(self):
        now = datetime.now(timezone.utc)
        trade_age = (now-self.last_trade_at).total_seconds() if self.last_trade_at else None
        depth_age = (now-self.last_depth_at).total_seconds() if self.last_depth_at else None
        valid = self.sequence_valid and depth_age is not None and 0 <= depth_age <= 5
        window_start_ms = int(now.timestamp() * 1000) - 60_000
        recent = [trade for trade in self.recent_trades if trade["event_time_ms"] >= window_start_ms]
        buy_volume = sum(trade["quantity"] for trade in recent if not trade["buyer_is_maker"])
        sell_volume = sum(trade["quantity"] for trade in recent if trade["buyer_is_maker"])
        total_volume = buy_volume + sell_volume
        delta = buy_volume - sell_volume
        bids = sorted(self.bids.items(), reverse=True)[:20]
        asks = sorted(self.asks.items())[:20]
        return {"market_type":MARKET_TYPE,"symbol":self.symbol,"status":self.status,
            "sequence_valid":bool(valid),"depth_ready":bool(valid and bids and asks),
            "snapshot_update_id":getattr(self,"snapshot_update_id",None),"last_update_id":self.last_update_id,
            "trade_count":self.trade_count,"last_trade":self.last_trade,
            "trade_flow_60s":{"window_start_ms":window_start_ms,"window_seconds":60,
                "trade_count":len(recent),"buy_volume":buy_volume,"sell_volume":sell_volume,
                "total_volume":total_volume,"delta":delta,
                "delta_ratio":delta/total_volume if total_volume>0 else None,
                "coverage":"OBSERVED_STREAM_WINDOW_NOT_PROVEN_COMPLETE"},
            "trade_age_seconds":round(trade_age,3) if trade_age is not None else None,
            "depth_age_seconds":round(depth_age,3) if depth_age is not None else None,
            "bids":[{"price":str(p),"quantity":str(q)} for p,q in bids],
            "asks":[{"price":str(p),"quantity":str(q)} for p,q in asks],
            "gap_count":self.gap_count,"dropped_events":self.dropped_events,
            "last_error":self.last_error,"coverage":"OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE"}

    async def run(self, client, stop_event, on_update=None):
        attempt = 0
        while not stop_event.is_set():
            receiver = None
            try:
                self.status = "CONNECTING"; self.sequence_valid = False
                self.last_update_id = None; self.bids = {}; self.asks = {}
                self.recent_trades.clear(); self.last_trade = None; self.last_trade_at = None
                self.session_id = uuid.uuid4().hex
                async with self.websocket_factory(self.stream_url,ping_interval=20,ping_timeout=60,
                    close_timeout=10,open_timeout=10,max_size=1048576,max_queue=256) as websocket:
                    self.status = "BOOTSTRAPPING"
                    receiver, queue = await self._bootstrap(websocket,client,stop_event)
                    self.status = "LIVE"; self.last_error = None; attempt = 0
                    if on_update: await on_update(self.snapshot())
                    while not stop_event.is_set():
                        if receiver.done():
                            error = receiver.exception()
                            if error is not None: raise error
                            raise UsdmStreamError("Futures WebSocket receiver stopped unexpectedly.")
                        try: kind,data,received_ms = await asyncio.wait_for(queue.get(),timeout=1.0)
                        except asyncio.TimeoutError:
                            if on_update: await on_update(self.snapshot())
                            continue
                        self.last_message_at = datetime.now(timezone.utc)
                        if kind == "aggTrade": self._apply_trade(data,received_ms)
                        else:
                            normalized = normalize_usdm_depth_update(self.symbol,data,received_at_ms=received_ms)
                            self._apply_depth(normalized)
                        if on_update: await on_update(self.snapshot())
                    receiver.cancel()
                    await asyncio.gather(receiver,return_exceptions=True)
            except asyncio.CancelledError:
                if receiver: receiver.cancel()
                raise
            except Exception as exc:
                if receiver:
                    receiver.cancel()
                    await asyncio.gather(receiver,return_exceptions=True)
                self.sequence_valid = False; self.status = "RECONNECTING"
                self.last_error = f"{type(exc).__name__}: {exc}"
                if on_update: await on_update(self.snapshot())
                delay=min(self.reconnect_max_seconds,self.reconnect_initial_seconds*(2**min(attempt,8)))
                attempt += 1
                try: await asyncio.wait_for(stop_event.wait(),timeout=delay)
                except asyncio.TimeoutError: pass
        self.sequence_valid = False; self.status = "STOPPED"
        if on_update: await on_update(self.snapshot())

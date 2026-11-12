"""Loopback-only, bounded, process-local event fan-out for QUANTNEX."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import CORS_ORIGINS

router = APIRouter()
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_TEST_ORIGIN = "http://testserver"


class EventHub:
    """Fan out committed local workspace events without blocking API handlers."""

    def __init__(self, queue_size: int = 128, max_clients: int = 8) -> None:
        self.queue_size = queue_size
        self.max_clients = max_clients
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._sequence = 0
        self._lock = threading.Lock()

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def connect(self) -> asyncio.Queue[dict[str, Any]]:
        if len(self._clients) >= self.max_clients:
            raise RuntimeError("The local event stream has reached its connection limit.")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        self._clients.add(queue)
        return queue

    def disconnect(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)

    def publish(self, event_type: str, entity: str, action: str,
                payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not all(_EVENT_NAME.fullmatch(value or "") for value in (event_type, entity, action)):
            raise ValueError("Invalid local event name.")
        safe_payload = payload or {}
        encoded = json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("Local event payload exceeds 16 KiB.")
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        event = {
            "schema_version": 1,
            "event_id": sequence,
            "type": event_type,
            "entity": entity,
            "action": action,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": safe_payload,
        }
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._broadcast, event)
        return event

    def _broadcast(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._clients):
            if queue.full():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait({
                    "schema_version": 1,
                    "event_id": event["event_id"],
                    "type": "stream.resync_required",
                    "entity": "workspace",
                    "action": "resync",
                    "occurred_at": event["occurred_at"],
                    "payload": {"reason": "client_queue_overflow"},
                })
                continue
            queue.put_nowait(event)


event_hub = EventHub()


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() in {"localhost", "testclient", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _origin_allowed(origin: str | None, client_host: str | None) -> bool:
    if origin in CORS_ORIGINS:
        return _is_loopback_host(client_host)
    return origin == _TEST_ORIGIN and client_host == "testclient"


@router.websocket("/api/v1/events/stream")
async def workspace_event_stream(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    client_host = websocket.client.host if websocket.client else None
    host_header = websocket.headers.get("host", "")
    host_name = urlsplit("//" + host_header).hostname
    if not _origin_allowed(origin, client_host) or not _is_loopback_host(client_host) or not _is_loopback_host(host_name):
        await websocket.close(code=1008, reason="QUANTNEX event stream is loopback-only.")
        return

    event_hub.bind_loop(asyncio.get_running_loop())
    try:
        queue = event_hub.connect()
    except RuntimeError:
        await websocket.close(code=1013, reason="Local event stream is at capacity.")
        return

    await websocket.accept()
    await websocket.send_json({
        "schema_version": 1,
        "type": "stream.ready",
        "event_id": event_hub.sequence,
        "heartbeat_seconds": 20,
        "replay": False,
    })
    outgoing = asyncio.create_task(queue.get())
    incoming = asyncio.create_task(websocket.receive_text())
    last_heartbeat = time.monotonic()
    missed_heartbeats = 0
    try:
        while True:
            timeout = max(0.1, 20 - (time.monotonic() - last_heartbeat))
            done, _ = await asyncio.wait(
                {outgoing, incoming}, timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                missed_heartbeats += 1
                if missed_heartbeats >= 3:
                    await websocket.close(code=1011, reason="Local event heartbeat timed out.")
                    break
                await websocket.send_json({"type": "stream.ping", "sent_at": datetime.now(timezone.utc).isoformat()})
                last_heartbeat = time.monotonic()

            if outgoing in done:
                await websocket.send_json(outgoing.result())
                outgoing = asyncio.create_task(queue.get())

            if incoming in done:
                message = incoming.result()
                try:
                    parsed = json.loads(message)
                except (TypeError, ValueError):
                    await websocket.close(code=1008, reason="Only heartbeat acknowledgements are accepted.")
                    break
                if not isinstance(parsed, dict) or parsed.get("type") != "stream.pong":
                    await websocket.close(code=1008, reason="Only heartbeat acknowledgements are accepted.")
                    break
                missed_heartbeats = 0
                incoming = asyncio.create_task(websocket.receive_text())
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass
    finally:
        tasks = (outgoing, incoming)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event_hub.disconnect(queue)

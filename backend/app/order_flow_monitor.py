"""Continuous, bounded capture of Binance Spot order-flow observations.

The worker keeps a small configured set of read-only streams warm so the
sequence-validated manager can persist one observation aligned to each UTC
one-minute candle. It does not archive every raw tick or claim full-session
coverage; stored snapshots remain bounded by the recorder retention policy.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Any

from sqlalchemy import select

from .database import SessionLocal
from .models import Preference

logger = logging.getLogger("quantnex.order_flow_monitor")

DEFAULT_ORDER_FLOW_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
MAX_ORDER_FLOW_MONITOR_SYMBOLS = 8
ORDER_FLOW_MONITOR_REFRESH_SECONDS = 15.0


def normalize_order_flow_monitor_symbols(value: Any) -> list[str]:
    """Validate and de-duplicate a bounded list of Binance Spot symbols."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = None
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_ORDER_FLOW_SYMBOLS)
    result: list[str] = []
    for item in value:
        symbol = str(item or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol) or symbol in result:
            continue
        result.append(symbol)
        if len(result) >= MAX_ORDER_FLOW_MONITOR_SYMBOLS:
            break
    return result or list(DEFAULT_ORDER_FLOW_SYMBOLS)


def get_recent_trade_count_baseline(symbol: str, *, now=None, lookback_minutes: int = 30) -> float | None:
    """Return a median of stored, validated per-minute trade counts when coverage is sufficient."""
    from datetime import datetime, timedelta, timezone
    from statistics import median
    from .order_flow_recorder import load_order_flow_observations

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    if isinstance(lookback_minutes, bool) or not isinstance(lookback_minutes, int) or not 5 <= lookback_minutes <= 240:
        raise ValueError("lookback_minutes must be between 5 and 240.")
    db = SessionLocal()
    try:
        rows = load_order_flow_observations(
            db, symbol, instant - timedelta(minutes=lookback_minutes), instant,
            limit=min(500, lookback_minutes + 5),
        )
    finally:
        db.close()
    counts = []
    for row in rows:
        flow = row.get("order_flow") if isinstance(row, dict) else None
        value = flow.get("trade_count") if isinstance(flow, dict) else None
        if isinstance(value, bool):
            continue
        try:
            count = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(count) and count > 0:
            counts.append(count)
    if len(counts) < 5:
        return None
    return float(median(counts[-lookback_minutes:]))


def _load_symbols() -> list[str]:
    db = SessionLocal()
    try:
        row = db.scalar(
            select(Preference)
            .where(Preference.key == "order_flow_monitor_symbols")
            .order_by(Preference.id.desc())
        )
        return normalize_order_flow_monitor_symbols(row.value if row else None)
    finally:
        db.close()


class BinanceSpotOrderFlowCaptureWorker:
    """Keep selected public Spot streams warm for minute-aligned observation capture."""

    def __init__(self, *, refresh_seconds: float = ORDER_FLOW_MONITOR_REFRESH_SECONDS) -> None:
        if not isinstance(refresh_seconds, (int, float)) or isinstance(refresh_seconds, bool) or refresh_seconds < 2:
            raise ValueError("refresh_seconds must be at least two seconds.")
        self.refresh_seconds = float(refresh_seconds)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_cycle_at: str | None = None
        self.last_error: str | None = None
        self.monitored_symbols: list[str] = []

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="quantnex-order-flow-capture-worker")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _warm_symbol(self, symbol: str) -> None:
        from .signal_engine import get_binance_spot_symbol_info
        from .binance_order_flow_manager import get_binance_spot_order_flow_manager

        info = await get_binance_spot_symbol_info(symbol)
        filters = info.get("filters") if isinstance(info, dict) else None
        price_filter = filters.get("PRICE_FILTER") if isinstance(filters, dict) else None
        tick_size = price_filter.get("tickSize") if isinstance(price_filter, dict) else None
        if not tick_size:
            raise ValueError(f"{symbol} has no valid Binance PRICE_FILTER tick size.")
        await get_binance_spot_order_flow_manager().get_snapshot(
            symbol, str(tick_size), wait_seconds=0.0
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last_error = None
                symbols = _load_symbols()
                self.monitored_symbols = symbols
                for symbol in symbols:
                    if self._stop.is_set():
                        break
                    try:
                        await self._warm_symbol(symbol)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.last_error = f"{symbol}: {type(exc).__name__}: {str(exc)[:180]}"
                        logger.warning("Order Flow capture warm-up failed for %s: %s", symbol, type(exc).__name__)
                from datetime import datetime, timezone
                self.last_cycle_at = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                logger.warning("Order Flow capture cycle failed: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.refresh_seconds)
            except asyncio.TimeoutError:
                pass


_WORKER = BinanceSpotOrderFlowCaptureWorker()


async def start_order_flow_capture_worker() -> None:
    await _WORKER.start()


async def stop_order_flow_capture_worker() -> None:
    await _WORKER.stop()


def get_order_flow_capture_status() -> dict[str, Any]:
    return {
        "running": _WORKER._task is not None and not _WORKER._task.done(),
        "symbols": list(_WORKER.monitored_symbols),
        "refresh_seconds": _WORKER.refresh_seconds,
        "last_cycle_at": _WORKER.last_cycle_at,
        "last_error": _WORKER.last_error,
        "capture_alignment": "ONE_OBSERVATION_PER_UTC_1M_CANDLE",
        "raw_tick_archive": False,
    }

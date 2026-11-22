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

from sqlalchemy import func, select

from .database import SessionLocal
from .models import OrderFlowObservation, Preference

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


def _parse_aware_utc(value: Any):
    """Parse an explicit timezone-aware timestamp; never guess a local timezone."""
    from datetime import datetime, timezone

    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(timezone.utc)


def get_minute_aligned_order_flow_snapshot(
    symbol: str,
    candle: dict[str, Any],
    *,
    now=None,
    max_trade_age_seconds: float = 15.0,
    max_depth_age_seconds: float = 5.0,
) -> dict[str, Any] | None:
    """Load the recorded Spot snapshot for one closed UTC M1 candle.

    The recorder captures near the final two seconds of each minute. This
    helper pairs that persisted sample with the exact candle minute and
    recomputes source ages at analysis time. A live stream's newest trade is
    deliberately not substituted because it usually belongs to the next
    minute and would be look-ahead/misaligned context for the closed candle.
    """
    from datetime import datetime, timedelta, timezone
    from .order_flow_recorder import load_order_flow_observations

    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized):
        raise ValueError("A valid Binance Spot symbol is required.")
    if not isinstance(candle, dict):
        return None
    candle_start = _parse_aware_utc(candle.get("time") or candle.get("open_time"))
    if candle_start is None or candle_start.second != 0 or candle_start.microsecond != 0:
        return None

    instant = now or datetime.now(timezone.utc)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime.")
    instant = instant.astimezone(timezone.utc)

    for value, label in (
        (max_trade_age_seconds, "max_trade_age_seconds"),
        (max_depth_age_seconds, "max_depth_age_seconds"),
    ):
        if isinstance(value, bool):
            raise ValueError(f"{label} must be finite and positive.")
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{label} must be finite and positive.") from None
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(f"{label} must be finite and positive.")
        if label == "max_trade_age_seconds":
            max_trade_age_seconds = numeric
        else:
            max_depth_age_seconds = numeric

    candle_end = candle_start + timedelta(minutes=1)
    if candle_end > instant:
        return None

    db = SessionLocal()
    try:
        rows = load_order_flow_observations(
            db, normalized, candle_start, candle_end, limit=2
        )
    finally:
        db.close()
    if len(rows) != 1:
        return None

    payload = rows[0]
    storage = payload.get("storage") if isinstance(payload, dict) else None
    flow = payload.get("order_flow") if isinstance(payload, dict) else None
    trade_state = payload.get("trade_state") if isinstance(payload, dict) else None
    depth_book = payload.get("depth_book") if isinstance(payload, dict) else None
    if not all(isinstance(value, dict) for value in (storage, flow, trade_state, depth_book)):
        return None
    if payload.get("market_type") != "BINANCE_SPOT" or flow.get("market_type") != "BINANCE_SPOT":
        return None
    if flow.get("feed_mode") != "PUBLIC_WEBSOCKET_STREAM":
        return None
    if flow.get("depth_is_continuous") is not True:
        return None
    if trade_state.get("coverage_complete") is not True or trade_state.get("gap_detected") is not False:
        return None
    if depth_book.get("valid") is not True or depth_book.get("sequence_validated") is not True:
        return None
    if not isinstance(flow.get("order_book"), dict):
        return None
    provenance = payload.get("data_provenance")
    if not isinstance(provenance, dict) or provenance.get("candle_volume_used") is not False:
        return None

    try:
        bucket = storage.get("sample_bucket")
        if isinstance(bucket, bool) or not isinstance(bucket, int):
            return None
        if bucket != int(candle_start.timestamp()) // 60:
            return None
        captured_at = _parse_aware_utc(storage.get("captured_at") or payload.get("captured_at"))
        last_trade_at = _parse_aware_utc(flow.get("last_trade_at"))
        depth_observed_at = _parse_aware_utc(flow.get("depth_observed_at"))
        if captured_at is None or last_trade_at is None or depth_observed_at is None:
            return None
        if not candle_start <= captured_at < candle_end:
            return None
        if not candle_start <= last_trade_at < candle_end:
            return None
        elapsed = (instant - captured_at).total_seconds()
        if elapsed < -2:
            return None
        trade_age = (instant - last_trade_at).total_seconds()
        depth_age = (instant - depth_observed_at).total_seconds()
        if (
            trade_age < -2 or depth_age < -2
            or trade_age > max_trade_age_seconds
            or depth_age > max_depth_age_seconds
            or captured_at - last_trade_at > timedelta(seconds=max_trade_age_seconds)
            or captured_at - depth_observed_at > timedelta(seconds=max_depth_age_seconds)
            or depth_observed_at > captured_at + timedelta(seconds=2)
        ):
            return None
        for key in ("trade_count", "delta_ratio"):
            value = flow.get(key)
            if isinstance(value, bool) or not math.isfinite(float(value)):
                return None
        if float(flow.get("trade_count")) < 1 or not -1 <= float(flow.get("delta_ratio")) <= 1:
            return None
    except (TypeError, ValueError, OverflowError):
        return None

    # Flatten only the stored, verified feature fields expected by the pattern
    # classifier. Keep source provenance and exact observation timing attached.
    aligned = dict(flow)
    aligned.update({
        "market_type": payload.get("market_type"),
        "data_provenance": provenance,
        "depth_age_seconds": max(0.0, depth_age),
        "trade_data_age_seconds": max(0.0, trade_age),
        "captured_at": captured_at.isoformat(),
        "snapshot_age_seconds": max(0.0, elapsed),
        "observation_minute": candle_start.isoformat(),
    })
    return aligned


def get_recent_trade_count_baseline(
    symbol: str,
    *,
    now=None,
    lookback_minutes: int = 30,
) -> float | None:
    """Return a median only from at least five consecutive prior UTC minute samples."""
    from datetime import datetime, timedelta, timezone
    from statistics import median
    from .order_flow_recorder import load_order_flow_observations

    instant = now or datetime.now(timezone.utc)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    instant = instant.astimezone(timezone.utc)
    if isinstance(lookback_minutes, bool) or not isinstance(lookback_minutes, int) or not 5 <= lookback_minutes <= 240:
        raise ValueError("lookback_minutes must be between 5 and 240.")

    # Exclude the currently forming minute. The newest acceptable baseline
    # observation is the immediately preceding UTC minute.
    window_end = instant.replace(second=0, microsecond=0)
    expected_latest_bucket = int(window_end.timestamp()) // 60 - 1
    db = SessionLocal()
    try:
        rows = load_order_flow_observations(
            db, str(symbol).strip().upper(),
            window_end - timedelta(minutes=lookback_minutes), window_end,
            limit=min(500, lookback_minutes + 5),
        )
    finally:
        db.close()

    counts_by_bucket: dict[int, float] = {}
    for row in rows:
        storage = row.get("storage") if isinstance(row, dict) else None
        flow = row.get("order_flow") if isinstance(row, dict) else None
        if not isinstance(storage, dict) or not isinstance(flow, dict):
            continue
        bucket = storage.get("sample_bucket")
        value = flow.get("trade_count")
        if isinstance(bucket, bool) or not isinstance(bucket, int) or isinstance(value, bool):
            continue
        try:
            count = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(count) and count > 0:
            counts_by_bucket[bucket] = count

    consecutive: list[float] = []
    for offset in range(lookback_minutes):
        bucket = expected_latest_bucket - offset
        count = counts_by_bucket.get(bucket)
        if count is None:
            break
        consecutive.append(count)
    if len(consecutive) < 5:
        return None
    return float(median(consecutive))


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
    from datetime import datetime, timedelta, timezone

    manager_status: dict[str, Any]
    try:
        from .binance_order_flow_manager import get_binance_spot_order_flow_manager

        manager = get_binance_spot_order_flow_manager()
        manager_status = {
            "active_streams": manager.active_stream_count,
            "max_streams": manager.max_streams,
            "last_captured_at": manager.last_capture_at,
            "last_capture_error": manager.last_capture_error,
        }
    except Exception as exc:
        manager_status = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}

    observation_count = 0
    latest_observation_at = None
    recorder_error = None
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cutoff_ms = int((now - timedelta(hours=24)).timestamp() * 1000)
        observation_count = int(
            db.query(func.count(OrderFlowObservation.id))
            .filter(
                OrderFlowObservation.market_type == "BINANCE_SPOT",
                OrderFlowObservation.captured_at_epoch_ms >= cutoff_ms,
            )
            .scalar() or 0
        )
        latest_epoch_ms = db.query(func.max(
            OrderFlowObservation.captured_at_epoch_ms
        )).filter(
            OrderFlowObservation.market_type == "BINANCE_SPOT"
        ).scalar()
        if latest_epoch_ms is not None:
            latest_observation_at = datetime.fromtimestamp(
                int(latest_epoch_ms) / 1000, timezone.utc
            ).isoformat()
    except Exception as exc:
        recorder_error = type(exc).__name__
    finally:
        db.close()

    return {
        "running": _WORKER._task is not None and not _WORKER._task.done(),
        "symbols": list(_WORKER.monitored_symbols),
        "refresh_seconds": _WORKER.refresh_seconds,
        "last_cycle_at": _WORKER.last_cycle_at,
        "last_error": _WORKER.last_error,
        "capture_alignment": "ONE_OBSERVATION_PER_UTC_1M_CANDLE",
        "raw_tick_archive": False,
        "manager": manager_status,
        "observations_last_24h": observation_count,
        "latest_observation_at": latest_observation_at,
        "recorder_error_type": recorder_error,
    }

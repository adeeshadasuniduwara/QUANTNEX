"""Bounded capture of verified Binance Spot order-flow feature snapshots.

The recorder stores one compact, UTC-minute feature snapshot per active symbol.
It is intentionally not a raw tick archive: it preserves the exact observed
AggTrade-derived features, a bounded footprint sample and sequence-validated
L2 levels so a later replay can align them with historical candles. Only
read-only public Spot streams are eligible.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import OrderFlowObservation

SAMPLE_INTERVAL_SECONDS = 60
DEFAULT_RETENTION_DAYS = 7
MAX_STORED_FOOTPRINT_BUCKETS = 32
MAX_STORED_BOOK_LEVELS = 20


def _aware_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime.")
    return value.astimezone(timezone.utc)


def _finite(value: Any, label: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite numeric data.")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be finite numeric data.") from None
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite numeric data.")
    return parsed


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")
    return value


def is_recordable_order_flow_snapshot(snapshot: dict[str, Any]) -> bool:
    """Return true only for fresh, contiguous, sequence-validated Spot data."""
    try:
        if not isinstance(snapshot, dict) or snapshot.get("signal_ready") is not True:
            return False
        symbol = str(snapshot.get("symbol") or "").upper()
        if not re.fullmatch(r"[A-Z0-9]{5,25}", symbol):
            return False
        if snapshot.get("market_type") != "BINANCE_SPOT":
            return False

        trade_state = snapshot.get("trade_state")
        depth_book = snapshot.get("depth_book")
        order_flow = snapshot.get("order_flow")
        if not all(isinstance(item, dict) for item in (trade_state, depth_book, order_flow)):
            return False
        if trade_state.get("coverage_complete") is not True or trade_state.get("gap_detected") is True:
            return False
        if depth_book.get("valid") is not True or depth_book.get("sequence_validated") is not True:
            return False
        if order_flow.get("market_type") != "BINANCE_SPOT":
            return False
        if order_flow.get("feed_mode") != "PUBLIC_WEBSOCKET_STREAM":
            return False
        if order_flow.get("depth_is_continuous") is not True:
            return False
        if order_flow.get("cvd_status") != "COMPLETE_SINCE_STATE_SEED":
            return False

        trade_id = _non_negative_int(trade_state.get("last_agg_trade_id"), "last aggregate-trade ID")
        depth_id = _non_negative_int(depth_book.get("last_update_id"), "depth update ID")
        if _non_negative_int(order_flow.get("depth_snapshot_update_id"), "order-flow depth update ID") != depth_id:
            return False
        if trade_id < 1:
            return False

        trade_age = _finite(order_flow.get("trade_data_age_seconds"), "trade age")
        depth_age = _finite(snapshot.get("depth_age_seconds"), "depth age")
        if trade_age is None or depth_age is None or not 0 <= trade_age <= 15 or not 0 <= depth_age <= 5:
            return False

        if _finite(order_flow.get("cvd_value"), "CVD") is None:
            return False
        for key in ("trade_count", "delta", "delta_ratio"):
            value = order_flow.get(key)
            if key == "trade_count":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    return False
            elif _finite(value, key) is None:
                return False

        book_metrics = order_flow.get("order_book")
        provenance = order_flow.get("data_provenance")
        sources = order_flow.get("data_sources")
        if not isinstance(book_metrics, dict) or not isinstance(provenance, dict) or not isinstance(sources, dict):
            return False
        if provenance.get("candle_volume_used") is not False:
            return False
        if "aggressor" not in str(provenance.get("bid_ask_semantics") or "").lower():
            return False
        if not isinstance(sources.get("stream"), str) or not sources["stream"].startswith("wss://"):
            return False
        for key in ("spread_bps", "depth_imbalance", "microprice", "mid_price"):
            if _finite(book_metrics.get(key), f"order-book {key}") is None:
                return False

        for key in ("depth_observed_at", "last_trade_at"):
            stamp = datetime.fromisoformat(str(order_flow.get(key) or "").replace("Z", "+00:00"))
            _aware_utc(stamp, key)
        if not isinstance(depth_book.get("bids"), list) or not depth_book["bids"]:
            return False
        if not isinstance(depth_book.get("asks"), list) or not depth_book["asks"]:
            return False
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _compact_snapshot(snapshot: dict[str, Any], captured_at: datetime) -> str:
    order_flow = snapshot["order_flow"]
    trade_state = snapshot["trade_state"]
    depth_book = snapshot["depth_book"]
    footprint = order_flow.get("footprint")
    footprint_rows = footprint if isinstance(footprint, list) else []
    valid_footprint = [
        row for row in footprint_rows
        if isinstance(row, dict)
        and _finite(row.get("price"), "footprint price") is not None
        and _finite(row.get("buy_volume"), "footprint buy volume") is not None
        and _finite(row.get("sell_volume"), "footprint sell volume") is not None
    ]
    top_footprint = sorted(
        valid_footprint,
        key=lambda row: (
            -(_finite(row.get("buy_volume"), "buy volume") + _finite(row.get("sell_volume"), "sell volume")),
            _finite(row.get("price"), "footprint price"),
        ),
    )[:MAX_STORED_FOOTPRINT_BUCKETS]
    top_footprint.sort(key=lambda row: _finite(row.get("price"), "footprint price"))

    order_flow_keys = (
        "market_type", "data_provenance", "trade_count", "unique_aggregate_trade_ids",
        "first_trade_at", "last_trade_at", "trade_data_age_seconds", "buy_volume",
        "sell_volume", "delta", "delta_ratio", "window_cumulative_delta",
        "window_delta_scope", "cvd_value", "cvd_status", "cvd_scope", "quote_delta",
        "session_timezone", "session_date_utc", "session_delta", "session_delta_sample",
        "session_delta_coverage_complete", "session_delta_scope", "session_start_trade_id",
        "volume_profile", "order_book", "quality", "depth_is_continuous",
        "depth_snapshot_update_id", "depth_observed_at", "data_sources", "feed_mode",
    )
    compact_order_flow = {key: order_flow[key] for key in order_flow_keys if key in order_flow}
    compact_order_flow["footprint"] = top_footprint
    compact_order_flow["footprint_bucket_count_total"] = len(footprint_rows)
    compact_order_flow["footprint_buckets_stored"] = len(top_footprint)

    payload = {
        "capture_version": 1,
        "capture_scope": "ONE_UTC_MINUTE_FEATURE_SNAPSHOT",
        "captured_at": captured_at.isoformat(),
        "symbol": snapshot["symbol"],
        "market_type": "BINANCE_SPOT",
        "trade_state": {
            key: trade_state.get(key) for key in (
                "last_agg_trade_id", "cumulative_delta_observed", "cumulative_quote_delta_observed",
                "cvd_value", "cvd_status", "cvd_scope", "session_date_utc", "session_delta",
                "session_delta_coverage_complete", "last_trade_time_ms", "applied_trade_count",
                "duplicate_count", "out_of_order_count",
            )
        },
        "depth_book": {
            "valid": depth_book.get("valid"),
            "sequence_validated": depth_book.get("sequence_validated"),
            "last_update_id": depth_book.get("last_update_id"),
            "bids": depth_book["bids"][:MAX_STORED_BOOK_LEVELS],
            "asks": depth_book["asks"][:MAX_STORED_BOOK_LEVELS],
        },
        "order_flow": compact_order_flow,
        "data_provenance": snapshot.get("data_provenance"),
        "depth_age_seconds": snapshot.get("depth_age_seconds"),
        "last_message_at": snapshot.get("last_message_at"),
    }
    return json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)


def record_order_flow_observation(
    db: Session,
    snapshot: dict[str, Any],
    *,
    captured_at: datetime | None = None,
    prune_before: datetime | None = None,
) -> dict[str, Any]:
    """Persist one eligible symbol/minute snapshot; duplicates are harmless."""
    if not is_recordable_order_flow_snapshot(snapshot):
        return {"recorded": False, "reason": "SNAPSHOT_NOT_READY_OR_NOT_SEQUENCE_VALIDATED"}
    captured = _aware_utc(captured_at or datetime.now(timezone.utc), "captured_at")
    captured_epoch_ms = int(captured.timestamp() * 1000)
    sample_bucket = int(captured.timestamp()) // SAMPLE_INTERVAL_SECONDS
    try:
        payload_json = _compact_snapshot(snapshot, captured)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"recorded": False, "reason": f"INVALID_SNAPSHOT_PAYLOAD: {exc}"}

    existing = db.query(OrderFlowObservation.id).filter(
        OrderFlowObservation.market_type == "BINANCE_SPOT",
        OrderFlowObservation.symbol == snapshot["symbol"],
        OrderFlowObservation.sample_bucket == sample_bucket,
    ).first()
    if existing:
        return {"recorded": False, "reason": "DUPLICATE_UTC_MINUTE_BUCKET", "sample_bucket": sample_bucket}

    cutoff_ms = None
    if prune_before is not None:
        cutoff_ms = int(_aware_utc(prune_before, "prune_before").timestamp() * 1000)
        db.query(OrderFlowObservation).filter(
            OrderFlowObservation.captured_at_epoch_ms < cutoff_ms
        ).delete(synchronize_session=False)

    order_flow = snapshot["order_flow"]
    trade_state = snapshot["trade_state"]
    book = order_flow["order_book"]
    row = OrderFlowObservation(
        market_type="BINANCE_SPOT",
        symbol=snapshot["symbol"],
        sample_bucket=sample_bucket,
        captured_at=captured,
        captured_at_epoch_ms=captured_epoch_ms,
        last_agg_trade_id=trade_state["last_agg_trade_id"],
        depth_update_id=order_flow["depth_snapshot_update_id"],
        trade_count=order_flow["trade_count"],
        trade_data_age_seconds=float(order_flow["trade_data_age_seconds"]),
        depth_age_seconds=float(snapshot["depth_age_seconds"]),
        delta=float(order_flow["delta"]),
        delta_ratio=float(order_flow["delta_ratio"]),
        cvd_value=float(order_flow["cvd_value"]),
        cvd_status=str(order_flow["cvd_status"]),
        session_delta=(
            float(order_flow["session_delta"])
            if order_flow.get("session_delta") is not None else None
        ),
        session_delta_complete=order_flow.get("session_delta_coverage_complete") is True,
        spread_bps=float(book["spread_bps"]),
        depth_imbalance=float(book["depth_imbalance"]),
        snapshot_json=payload_json,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        return {"recorded": False, "reason": "DUPLICATE_UTC_MINUTE_BUCKET", "sample_bucket": sample_bucket}
    except Exception:
        db.rollback()
        raise
    return {
        "recorded": True,
        "id": row.id,
        "symbol": row.symbol,
        "sample_bucket": row.sample_bucket,
        "captured_at": captured.isoformat(),
        "pruned_before_epoch_ms": cutoff_ms,
    }


def load_order_flow_observations(
    db: Session,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Load chronological feature snapshots in a strict [start, end) UTC window."""
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized):
        raise ValueError("A valid Binance Spot symbol is required.")
    start_utc = _aware_utc(start, "start")
    end_utc = _aware_utc(end, "end")
    if end_utc <= start_utc:
        raise ValueError("end must be later than start.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50000:
        raise ValueError("limit must be between 1 and 50000.")
    start_ms = int(start_utc.timestamp() * 1000)
    end_ms = int(end_utc.timestamp() * 1000)
    rows = db.query(OrderFlowObservation).filter(
        OrderFlowObservation.market_type == "BINANCE_SPOT",
        OrderFlowObservation.symbol == normalized,
        OrderFlowObservation.captured_at_epoch_ms >= start_ms,
        OrderFlowObservation.captured_at_epoch_ms < end_ms,
    ).order_by(
        OrderFlowObservation.captured_at_epoch_ms.asc(),
        OrderFlowObservation.id.asc(),
    ).limit(limit).all()
    results = []
    for row in rows:
        payload = json.loads(row.snapshot_json)
        payload["storage"] = {
            "id": row.id,
            "sample_bucket": row.sample_bucket,
            "captured_at_epoch_ms": row.captured_at_epoch_ms,
            "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            "last_agg_trade_id": row.last_agg_trade_id,
            "depth_update_id": row.depth_update_id,
        }
        results.append(payload)
    return results

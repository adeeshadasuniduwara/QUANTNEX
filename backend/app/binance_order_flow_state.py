"""Deterministic state machines for Binance Spot order-flow streams.

No network connections are opened here. The future WebSocket adapter must feed
aggregate trades and diff-depth events into these classes and obey their
incomplete/resync states before exposing CVD or book metrics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


class OrderFlowStateError(ValueError):
    """Raised when a stream event cannot be safely applied."""


def _int_value(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise OrderFlowStateError(f"{label} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise OrderFlowStateError(f"{label} must be an integer.") from None
    if str(parsed) != str(value).strip():
        raise OrderFlowStateError(f"{label} must be an exact integer.")
    return parsed


def _decimal_value(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OrderFlowStateError(f"{label} must be a decimal number.") from None
    if not parsed.is_finite():
        raise OrderFlowStateError(f"{label} must be finite.")
    return parsed


def _parse_agg_trade(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, int, bool, date, Decimal, Decimal]:
    if not isinstance(row, dict):
        raise OrderFlowStateError("Aggregate trade event must be an object.")
    trade_id = _int_value(row.get("a"), "aggregate trade ID")
    price = _decimal_value(row.get("p"), "trade price")
    quantity = _decimal_value(row.get("q"), "trade quantity")
    timestamp_ms = _int_value(row.get("T"), "trade timestamp")
    buyer_is_maker = row.get("m")
    if trade_id < 0 or timestamp_ms < 0 or price <= 0 or quantity <= 0:
        raise OrderFlowStateError("Aggregate trade event contains non-positive or negative values.")
    if not isinstance(buyer_is_maker, bool):
        raise OrderFlowStateError("Aggregate trade buyer-is-maker flag must be boolean.")
    try:
        event_date = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        raise OrderFlowStateError("Aggregate trade timestamp is outside the supported UTC range.") from None
    sign = Decimal("-1") if buyer_is_maker else Decimal("1")
    return trade_id, price, quantity, timestamp_ms, buyer_is_maker, event_date, quantity * sign, price * quantity * sign


@dataclass
class AggTradeCvdState:
    """Contiguous aggregate-trade delta state with explicit completeness.

    Call begin_utc_session() with the first aggTrade ID returned by a UTC
    session-start REST probe, then replay every ID from that point. A state
    started from an arbitrary live event remains incomplete until rebuilt from
    a known anchor. On an ID gap, ingest pauses until apply_backfill() fills it.
    """

    symbol: str
    last_agg_trade_id: int | None = None
    cumulative_delta: Decimal = Decimal("0")
    cumulative_quote_delta: Decimal = Decimal("0")
    session_delta: Decimal = Decimal("0")
    session_quote_delta: Decimal = Decimal("0")
    session_date_utc: date | None = None
    session_start_trade_id: int | None = None
    coverage_complete: bool = False
    session_coverage_complete: bool = False
    gap_detected: bool = False
    gap_expected_id: int | None = None
    gap_observed_id: int | None = None
    applied_trade_count: int = 0
    duplicate_count: int = 0
    out_of_order_count: int = 0
    last_trade_time_ms: int | None = None
    _coverage_before_gap: bool = field(default=False, repr=False)
    _session_coverage_before_gap: bool = field(default=False, repr=False)
    _session_date_before_gap: date | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.symbol = str(self.symbol).upper()
        if not re.fullmatch(r"[A-Z0-9]{5,25}", self.symbol):
            raise OrderFlowStateError("Invalid Binance Spot symbol for stream state.")

    def begin_utc_session(self, first_trade_id: int, session_date: date) -> None:
        """Seed a session-complete state at the known first trade ID for a UTC date."""
        first_id = _int_value(first_trade_id, "first session trade ID")
        if first_id < 0 or not isinstance(session_date, date) or isinstance(session_date, datetime):
            raise OrderFlowStateError("A non-negative first trade ID and UTC date (not datetime) are required.")
        self.last_agg_trade_id = first_id - 1
        self.cumulative_delta = Decimal("0")
        self.cumulative_quote_delta = Decimal("0")
        self.session_delta = Decimal("0")
        self.session_quote_delta = Decimal("0")
        self.session_date_utc = session_date
        self.session_start_trade_id = first_id
        self.coverage_complete = True
        self.session_coverage_complete = True
        self.gap_detected = False
        self.gap_expected_id = None
        self.gap_observed_id = None
        self.applied_trade_count = 0
        self.duplicate_count = 0
        self.out_of_order_count = 0
        self.last_trade_time_ms = None
        self._coverage_before_gap = False
        self._session_coverage_before_gap = False
        self._session_date_before_gap = None

    def begin_stream_seed(self, first_trade_id: int, first_trade_time_ms: int) -> None:
        """Start a complete CVD baseline from a bounded stream bootstrap window.

        This makes CVD complete only since the supplied seed trade, not from
        UTC session start. Session delta deliberately remains incomplete until
        a separate full-session anchor/backfill proves its coverage.
        """
        first_id = _int_value(first_trade_id, "first stream seed trade ID")
        timestamp_ms = _int_value(first_trade_time_ms, "first stream seed timestamp")
        if first_id < 0 or timestamp_ms < 0:
            raise OrderFlowStateError("Stream seed trade ID and timestamp must be non-negative.")
        try:
            seed_date = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            raise OrderFlowStateError("Stream seed timestamp is outside the supported UTC range.") from None

        self.last_agg_trade_id = first_id - 1
        self.cumulative_delta = Decimal("0")
        self.cumulative_quote_delta = Decimal("0")
        self.session_delta = Decimal("0")
        self.session_quote_delta = Decimal("0")
        self.session_date_utc = seed_date
        self.session_start_trade_id = None
        self.coverage_complete = True
        self.session_coverage_complete = False
        self.gap_detected = False
        self.gap_expected_id = None
        self.gap_observed_id = None
        self.applied_trade_count = 0
        self.duplicate_count = 0
        self.out_of_order_count = 0
        self.last_trade_time_ms = None
        self._coverage_before_gap = False
        self._session_coverage_before_gap = False
        self._session_date_before_gap = None

    def _mark_gap(self, expected: int, observed: int | None) -> None:
        if not self.gap_detected:
            self._coverage_before_gap = self.coverage_complete
            self._session_coverage_before_gap = self.session_coverage_complete
            self._session_date_before_gap = self.session_date_utc
        self.coverage_complete = False
        self.session_coverage_complete = False
        self.gap_detected = True
        self.gap_expected_id = expected
        self.gap_observed_id = observed

    def _apply_contiguous(
        self,
        parsed: tuple[int, Decimal, Decimal, int, bool, date, Decimal, Decimal],
    ) -> None:
        trade_id, _price, _quantity, timestamp_ms, _buyer_is_maker, event_date, signed_qty, signed_quote = parsed
        if self.last_trade_time_ms is not None and timestamp_ms < self.last_trade_time_ms:
            raise OrderFlowStateError("Aggregate trade timestamps must not move backwards.")
        if self.session_date_utc is None:
            self.session_date_utc = event_date
            self.session_coverage_complete = False
        elif event_date != self.session_date_utc:
            self.session_date_utc = event_date
            self.session_delta = Decimal("0")
            self.session_quote_delta = Decimal("0")
            self.session_start_trade_id = None
            self.session_coverage_complete = False
        self.cumulative_delta += signed_qty
        self.cumulative_quote_delta += signed_quote
        self.session_delta += signed_qty
        self.session_quote_delta += signed_quote
        self.last_agg_trade_id = trade_id
        self.last_trade_time_ms = timestamp_ms
        self.applied_trade_count += 1

    def ingest(self, row: dict[str, Any]) -> str:
        """Apply one live aggTrade event or return an explicit gap/duplicate state."""
        if self.gap_detected:
            return "GAP_PENDING"
        try:
            parsed = _parse_agg_trade(row)
        except OrderFlowStateError:
            if self.last_agg_trade_id is not None:
                expected = self.last_agg_trade_id + 1
                self._mark_gap(expected, expected)
            raise
        trade_id = parsed[0]
        if self.last_agg_trade_id is None:
            self.last_agg_trade_id = trade_id - 1
            self.session_date_utc = parsed[5]
            self.coverage_complete = False
            self.session_coverage_complete = False
        if trade_id <= self.last_agg_trade_id:
            if trade_id == self.last_agg_trade_id:
                self.duplicate_count += 1
                return "DUPLICATE"
            self.out_of_order_count += 1
            return "OUT_OF_ORDER"
        expected = self.last_agg_trade_id + 1
        if trade_id != expected:
            self._mark_gap(expected, trade_id)
            return "GAP_DETECTED"
        try:
            self._apply_contiguous(parsed)
        except OrderFlowStateError:
            self._mark_gap(expected, trade_id)
            raise
        return "APPLIED"

    def apply_backfill(self, rows: list[dict[str, Any]]) -> str:
        """Apply a REST fromId backfill; completeness returns only after the gap is closed."""
        if not self.gap_detected or self.last_agg_trade_id is None:
            raise OrderFlowStateError("Backfill is only valid while an aggregate-trade ID gap is open.")
        if not isinstance(rows, list):
            raise OrderFlowStateError("Aggregate-trade backfill must be a list.")
        for row in rows:
            parsed = _parse_agg_trade(row)
            trade_id = parsed[0]
            if trade_id <= self.last_agg_trade_id:
                continue
            expected = self.last_agg_trade_id + 1
            if trade_id != expected:
                return "BACKFILL_GAP_REMAINS"
            self._apply_contiguous(parsed)
        if self.gap_observed_id is not None and self.last_agg_trade_id >= self.gap_observed_id:
            self.gap_detected = False
            self.gap_expected_id = None
            self.gap_observed_id = None
            self.coverage_complete = self._coverage_before_gap
            self.session_coverage_complete = (
                self._session_coverage_before_gap
                and self.session_date_utc == self._session_date_before_gap
            )
            self._coverage_before_gap = False
            self._session_coverage_before_gap = False
            self._session_date_before_gap = None
            return "RECOVERED"
        return "BACKFILL_INCOMPLETE"

    def snapshot(self) -> dict[str, Any]:
        if self.gap_detected:
            cvd_status = "INCOMPLETE_ID_GAP"
        elif not self.coverage_complete:
            cvd_status = "INCOMPLETE_STREAM_START"
        else:
            cvd_status = "COMPLETE_SINCE_STATE_SEED"
        return {
            "symbol": self.symbol,
            "last_agg_trade_id": self.last_agg_trade_id,
            "cumulative_delta_observed": float(self.cumulative_delta),
            "cumulative_quote_delta_observed": float(self.cumulative_quote_delta),
            "cvd_value": float(self.cumulative_delta) if self.coverage_complete and not self.gap_detected else None,
            "cvd_scope": "SINCE_STATE_SEED",
            "cvd_status": cvd_status,
            "session_date_utc": self.session_date_utc.isoformat() if self.session_date_utc else None,
            "session_delta": float(self.session_delta)
                if self.session_coverage_complete and not self.gap_detected else None,
            "session_quote_delta": float(self.session_quote_delta)
                if self.session_coverage_complete and not self.gap_detected else None,
            "session_delta_coverage_complete": self.session_coverage_complete and not self.gap_detected,
            "session_start_trade_id": self.session_start_trade_id,
            "coverage_complete": self.coverage_complete and not self.gap_detected,
            "gap_detected": self.gap_detected,
            "gap_expected_id": self.gap_expected_id,
            "gap_observed_id": self.gap_observed_id,
            "applied_trade_count": self.applied_trade_count,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "last_trade_time_ms": self.last_trade_time_ms,
        }


def _parse_levels(rows: list[list[Any]], label: str) -> dict[Decimal, Decimal]:
    if not isinstance(rows, list) or not rows:
        raise OrderFlowStateError(f"{label} snapshot levels must be a non-empty list.")
    levels: dict[Decimal, Decimal] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise OrderFlowStateError(f"{label} level must contain price and quantity.")
        price = _decimal_value(row[0], f"{label} price")
        quantity = _decimal_value(row[1], f"{label} quantity")
        if price <= 0 or quantity < 0:
            raise OrderFlowStateError(f"{label} level has an invalid price or quantity.")
        if quantity == 0:
            levels.pop(price, None)
        else:
            levels[price] = quantity
    if not levels:
        raise OrderFlowStateError(f"{label} snapshot has no positive-quantity levels.")
    return levels


@dataclass
class BinanceSpotDepthBook:
    """Binance Spot L2 snapshot/diff bridge with strict update-ID gap invalidation."""

    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    last_update_id: int | None = None
    valid: bool = False
    sequence_validated: bool = False
    gap_expected_id: int | None = None
    gap_observed_id: int | None = None

    def _invalidate(self, expected: int | None = None, observed: int | None = None) -> None:
        self.valid = False
        self.sequence_validated = False
        self.bids.clear()
        self.asks.clear()
        self.gap_expected_id = expected
        self.gap_observed_id = observed

    def _validate_spread(self) -> None:
        if not self.bids or not self.asks:
            raise OrderFlowStateError("Depth book requires positive bid and ask levels.")
        if max(self.bids) >= min(self.asks):
            raise OrderFlowStateError("Depth book is crossed or locked.")

    def load_snapshot(
        self,
        last_update_id: int,
        bids: list[list[Any]],
        asks: list[list[Any]],
        buffered_events: list[dict[str, Any]] | None = None,
    ) -> str:
        """Load REST snapshot, then bridge buffered diff events in received order."""
        update_id = _int_value(last_update_id, "snapshot lastUpdateId")
        if update_id < 0:
            raise OrderFlowStateError("Snapshot lastUpdateId must be non-negative.")
        self.valid = False
        self.sequence_validated = False
        self.gap_expected_id = None
        self.gap_observed_id = None
        try:
            new_bids = _parse_levels(bids, "bid")
            new_asks = _parse_levels(asks, "ask")
            self.bids = new_bids
            self.asks = new_asks
            self._validate_spread()
        except OrderFlowStateError:
            self._invalidate()
            raise
        self.last_update_id = update_id
        self.valid = True
        for event in buffered_events or []:
            result = self.apply_diff(event)
            if result in {"GAP_DETECTED", "INVALID_BOOK", "INVALID_EVENT", "RESYNC_REQUIRED"}:
                return result
        return "SNAPSHOT_BRIDGED" if self.sequence_validated else "SNAPSHOT_READY"

    def _apply_levels(self, target: dict[Decimal, Decimal], rows: list[list[Any]], label: str) -> None:
        if not isinstance(rows, list):
            raise OrderFlowStateError(f"Depth {label} updates must be a list.")
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise OrderFlowStateError(f"Depth {label} update must contain price and quantity.")
            price = _decimal_value(row[0], f"depth {label} price")
            quantity = _decimal_value(row[1], f"depth {label} quantity")
            if price <= 0 or quantity < 0:
                raise OrderFlowStateError(f"Depth {label} update has an invalid price or quantity.")
            if quantity == 0:
                target.pop(price, None)
            else:
                target[price] = quantity

    def apply_diff(self, event: dict[str, Any]) -> str:
        """Apply one diff event; any missing update ID invalidates the book until resnapshot."""
        if not self.valid or self.last_update_id is None:
            return "RESYNC_REQUIRED"
        try:
            if not isinstance(event, dict):
                raise OrderFlowStateError("Depth diff event must be an object.")
            first_id = _int_value(event.get("U"), "depth first update ID")
            final_id = _int_value(event.get("u"), "depth final update ID")
            if first_id < 0 or final_id < first_id:
                raise OrderFlowStateError("Depth diff event has invalid update IDs.")
            if final_id <= self.last_update_id:
                return "DUPLICATE"
            expected = self.last_update_id + 1
            if first_id > expected:
                self._invalidate(expected, first_id)
                return "GAP_DETECTED"
            if not first_id <= expected <= final_id:
                self._invalidate(expected, first_id)
                return "GAP_DETECTED"
            self._apply_levels(self.bids, event.get("b", []), "bid")
            self._apply_levels(self.asks, event.get("a", []), "ask")
            self._validate_spread()
            self.last_update_id = final_id
            self.sequence_validated = True
            self.gap_expected_id = None
            self.gap_observed_id = None
            return "APPLIED"
        except OrderFlowStateError:
            self._invalidate()
            return "INVALID_BOOK"

    def snapshot(self, limit: int = 20) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise OrderFlowStateError("Depth snapshot limit must be between 1 and 1000.")
        return {
            "valid": self.valid,
            "sequence_validated": self.sequence_validated,
            "last_update_id": self.last_update_id,
            "gap_expected_id": self.gap_expected_id,
            "gap_observed_id": self.gap_observed_id,
            "bids": [[str(price), str(quantity)] for price, quantity in sorted(self.bids.items(), reverse=True)[:limit]],
            "asks": [[str(price), str(quantity)] for price, quantity in sorted(self.asks.items())[:limit]],
        }

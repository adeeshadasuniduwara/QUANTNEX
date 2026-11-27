"""Export a bounded local Binance Spot raw-event archive for causal replay.

Run from the backend directory:
    python export_spot_order_flow_archive.py --symbol BTCUSDT \
      --start 2026-11-26T00:00:00Z --end 2026-11-27T00:00:00Z \
      --output exports/BTCUSDT-orderflow.json

The exporter reads the existing local database only. It never connects to Binance,
creates trades, changes strategy settings, or exports credentials.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from app.database import SessionLocal
from app.order_flow_raw_recorder import load_order_flow_market_events_by_receive_time


MAX_EXPORT_EVENTS = 5000
_ALLOWED_EVENT_TYPES = {"aggTrade", "depthUpdate", "depthSnapshot", "captureGap"}


class OrderFlowArchiveExportError(ValueError):
    """Raised when a retained local archive cannot be exported without truncation."""


def _parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OrderFlowArchiveExportError(f"{label} must be a timezone-aware ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise OrderFlowArchiveExportError(f"{label} must be a valid ISO timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OrderFlowArchiveExportError(f"{label} must include a timezone (UTC is recommended).")
    return parsed.astimezone(timezone.utc)


def parse_utc_range(start: str, end: str) -> tuple[int, int]:
    start_at = _parse_utc(start, "start")
    end_at = _parse_utc(end, "end")
    start_ms = int(start_at.timestamp() * 1000)
    end_ms = int(end_at.timestamp() * 1000)
    if end_ms <= start_ms:
        raise OrderFlowArchiveExportError("end must be later than start.")
    return start_ms, end_ms


def build_archive_document(
    symbol: str,
    start_ms: int,
    end_ms: int,
    loaded: dict[str, Any],
    *,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}", normalized_symbol):
        raise OrderFlowArchiveExportError("A valid Binance Spot symbol is required.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (start_ms, end_ms)):
        raise OrderFlowArchiveExportError("Archive range must use integer epoch milliseconds.")
    if start_ms <= 0 or end_ms <= start_ms:
        raise OrderFlowArchiveExportError("Archive receive-time range is invalid.")
    if not isinstance(loaded, dict):
        raise OrderFlowArchiveExportError("Raw event loader returned an invalid result.")
    if loaded.get("time_basis") != "RECEIVED_AT_MS":
        raise OrderFlowArchiveExportError("Raw archive must be selected by receive time.")
    if loaded.get("truncated") is not False:
        raise OrderFlowArchiveExportError(
            "Raw archive is truncated or its truncation state is unknown; narrow the time window and retry."
        )
    events = loaded.get("events")
    if not isinstance(events, list) or not events:
        raise OrderFlowArchiveExportError("No retained Binance Spot raw events exist in the requested window.")
    if len(events) > MAX_EXPORT_EVENTS:
        raise OrderFlowArchiveExportError(
            f"Export exceeds the {MAX_EXPORT_EVENTS}-event replay limit; narrow the time window."
        )
    total_count = loaded.get("total_count")
    returned_count = loaded.get("returned_count")
    if (
        isinstance(total_count, bool) or not isinstance(total_count, int)
        or isinstance(returned_count, bool) or not isinstance(returned_count, int)
        or total_count != len(events) or returned_count != len(events)
    ):
        raise OrderFlowArchiveExportError("Raw event count metadata does not match the returned archive.")

    normalized_events: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise OrderFlowArchiveExportError(f"Raw event {index} is not an object.")
        if event.get("market_type") != "BINANCE_SPOT" or event.get("symbol") != normalized_symbol:
            raise OrderFlowArchiveExportError("Every event must match the requested Binance Spot symbol.")
        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in _ALLOWED_EVENT_TYPES:
            raise OrderFlowArchiveExportError(f"Raw event {index} has an unsupported event type.")
        row_id = event.get("id")
        received_ms = event.get("received_at_ms")
        event_ms = event.get("event_time_ms")
        if (
            isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= 0
            or isinstance(received_ms, bool) or not isinstance(received_ms, int)
            or isinstance(event_ms, bool) or not isinstance(event_ms, int)
            or received_ms < start_ms or received_ms >= end_ms
            or event_ms <= 0 or event_ms > received_ms + 2000
            or row_id in seen_ids
        ):
            raise OrderFlowArchiveExportError(f"Raw event {index} has invalid identity or timestamps.")
        session_id = event.get("stream_session_id")
        source = event.get("source")
        if (
            not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id)
            or not isinstance(source, str)
            or source not in {"WEBSOCKET", "WEBSOCKET_BUFFER", "REST_BOOTSTRAP", "REST_GAP_BACKFILL"}
            or not isinstance(event.get("payload"), dict)
        ):
            raise OrderFlowArchiveExportError(f"Raw event {index} is missing valid source, session or payload data.")
        seen_ids.add(row_id)
        normalized_events.append(event)

    normalized_events.sort(key=lambda item: (item["received_at_ms"], item["id"]))
    counts = Counter(item["event_type"] for item in normalized_events)
    sessions = sorted({item["stream_session_id"] for item in normalized_events})
    capture_gaps = counts.get("captureGap", 0)
    exported_source = exported_at or datetime.now(timezone.utc)
    if exported_source.tzinfo is None or exported_source.utcoffset() is None:
        raise OrderFlowArchiveExportError("exported_at must be timezone-aware.")
    exported = exported_source.astimezone(timezone.utc)
    return {
        "manifest": {
            "schema_version": 1,
            "market_type": "BINANCE_SPOT",
            "symbol": normalized_symbol,
            "time_basis": "RECEIVED_AT_MS",
            "requested_start_ms": start_ms,
            "requested_end_ms_exclusive": end_ms,
            "requested_start_utc": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
            "requested_end_utc_exclusive": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(),
            "exported_at": exported.isoformat(),
            "event_count": len(normalized_events),
            "event_type_counts": dict(sorted(counts.items())),
            "stream_session_count": len(sessions),
            "stream_session_ids": sessions,
            "capture_gap_count": capture_gaps,
            "first_received_at_ms": normalized_events[0]["received_at_ms"],
            "last_received_at_ms": normalized_events[-1]["received_at_ms"],
            "query_truncated": False,
            "coverage_is_complete": False,
            "coverage_status": "BOUNDED_LOCAL_CAPTURE_NOT_PROVEN_COMPLETE",
            "aggressor_semantics": "Binance Spot aggTrade buyer-is-maker flag infers taker side; not consolidated quoted bid/ask volume.",
            "volume_provenance": "Only archived aggTrade payloads are included; OHLCV candle volume is not substituted.",
            "limitations": [
                "A contiguous bounded archive does not prove every exchange event was captured.",
                "The first captured trade is only a CVD seed; full UTC-session delta is not inferred.",
                "Any captureGap marker must remain a replay eligibility veto.",
                "The export contains no candles, execution quotes, account fees or broker fills.",
            ],
        },
        "events": normalized_events,
    }


def write_archive_atomic(path: str | Path, document: dict[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise OrderFlowArchiveExportError("Destination already exists; choose a new output path to avoid overwriting local data.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        return target
    except (OSError, TypeError, ValueError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise OrderFlowArchiveExportError(f"Could not write archive safely: {type(exc).__name__}: {exc}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Current Binance Spot symbol, e.g. BTCUSDT")
    parser.add_argument("--start", required=True, help="Inclusive timezone-aware ISO timestamp")
    parser.add_argument("--end", required=True, help="Exclusive timezone-aware ISO timestamp")
    parser.add_argument("--output", required=True, help="Destination JSON path")
    parser.add_argument("--limit", type=int, default=MAX_EXPORT_EVENTS, help="Maximum events (1–5000)")
    args = parser.parse_args(argv)

    try:
        if isinstance(args.limit, bool) or not 1 <= args.limit <= MAX_EXPORT_EVENTS:
            raise OrderFlowArchiveExportError(f"limit must be between 1 and {MAX_EXPORT_EVENTS}.")
        start_ms, end_ms = parse_utc_range(args.start, args.end)
        normalized_symbol = args.symbol.strip().upper()
        db = SessionLocal()
        try:
            loaded = load_order_flow_market_events_by_receive_time(
                db, normalized_symbol, start_ms, end_ms, limit=args.limit
            )
        finally:
            db.close()
        document = build_archive_document(normalized_symbol, start_ms, end_ms, loaded)
        output = write_archive_atomic(args.output, document)
    except OrderFlowArchiveExportError as exc:
        print(f"[ARCHIVE EXPORT ERROR] {type(exc).__name__}: {str(exc)[:240]}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Database-driver messages may contain connection details; keep them out
        # of the console and exported diagnostics.
        print(
            f"[ARCHIVE EXPORT ERROR] {type(exc).__name__}: local database read/export failed; "
            "check DATABASE_URL, table availability and the requested time range.",
            file=sys.stderr,
        )
        return 2

    manifest = document["manifest"]
    print(
        f"[ARCHIVE EXPORTED] {manifest['symbol']} | events={manifest['event_count']} | "
        f"stream_sessions={manifest['stream_session_count']} | capture_gaps={manifest['capture_gap_count']} | "
        f"coverage={manifest['coverage_status']} | output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

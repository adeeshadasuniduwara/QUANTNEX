from datetime import datetime, timezone
import json
from pathlib import Path

import export_spot_order_flow_archive as archive_export

import pytest

from export_spot_order_flow_archive import (
    OrderFlowArchiveExportError,
    build_archive_document,
    parse_utc_range,
    write_archive_atomic,
)


SESSION = "0123456789abcdef0123456789abcdef"
START_MS = 1_795_248_000_000


def _event(row_id=1, event_type="aggTrade"):
    stamp = START_MS + row_id * 100
    payload = (
        {"a": row_id, "p": "100", "q": "1", "T": stamp, "m": False}
        if event_type == "aggTrade"
        else {"gap_id": "a" * 32, "reason": "RAW_CAPTURE_QUEUE_OVERFLOW"}
    )
    return {
        "id": row_id,
        "market_type": "BINANCE_SPOT",
        "symbol": "BTCUSDT",
        "event_type": event_type,
        "event_key": str(row_id),
        "event_time_ms": stamp,
        "received_at_ms": stamp + 20,
        "candle_bucket_ms": stamp // 60_000 * 60_000,
        "source": "WEBSOCKET",
        "stream_session_id": SESSION,
        "sequence_first": None,
        "sequence_last": None,
        "payload": payload,
    }


def _loaded(events, *, truncated=False):
    return {
        "events": events,
        "total_count": len(events),
        "returned_count": len(events),
        "truncated": truncated,
        "time_basis": "RECEIVED_AT_MS",
    }


def test_parse_utc_range_requires_aware_ordered_timestamps():
    start, end = parse_utc_range("2026-11-26T00:00:00Z", "2026-11-27T00:00:00+00:00")
    assert end - start == 86_400_000
    with pytest.raises(OrderFlowArchiveExportError, match="timezone"):
        parse_utc_range("2026-11-26T00:00:00", "2026-11-27T00:00:00Z")
    with pytest.raises(OrderFlowArchiveExportError, match="later"):
        parse_utc_range("2026-11-27T00:00:00Z", "2026-11-26T00:00:00Z")


def test_archive_manifest_is_explicitly_bounded_and_counts_capture_gaps():
    events = [_event(1), _event(2), _event(3, "captureGap")]
    document = build_archive_document(
        "BTCUSDT", START_MS, START_MS + 10_000, _loaded(events),
        exported_at=datetime(2026, 11, 27, tzinfo=timezone.utc),
    )
    manifest = document["manifest"]
    assert manifest["event_count"] == 3
    assert manifest["event_type_counts"] == {"aggTrade": 2, "captureGap": 1}
    assert manifest["capture_gap_count"] == 1
    assert manifest["coverage_is_complete"] is False
    assert manifest["coverage_status"] == "BOUNDED_LOCAL_CAPTURE_NOT_PROVEN_COMPLETE"
    assert document["events"] == events


def test_archive_export_rejects_truncated_or_count_mismatched_windows():
    events = [_event(1)]
    with pytest.raises(OrderFlowArchiveExportError, match="truncated"):
        build_archive_document("BTCUSDT", START_MS, START_MS + 10_000, _loaded(events, truncated=True))
    loaded = _loaded(events)
    loaded["total_count"] = 2
    with pytest.raises(OrderFlowArchiveExportError, match="count metadata"):
        build_archive_document("BTCUSDT", START_MS, START_MS + 10_000, loaded)


@pytest.mark.parametrize("mutation", [
    {"symbol": "ETHUSDT"},
    {"market_type": "BINANCE_USDM_FUTURES"},
    {"received_at_ms": START_MS + 20_000},
    {"event_type": "unsupported"},
    {"stream_session_id": "invalid-session"},
    {"source": "UNKNOWN_SOURCE"},
    {"source": ["WEBSOCKET"]},
    {"event_type": ["aggTrade"]},
])
def test_archive_export_rejects_mixed_or_out_of_window_events(mutation):
    event = {**_event(1), **mutation}
    with pytest.raises(OrderFlowArchiveExportError):
        build_archive_document("BTCUSDT", START_MS, START_MS + 10_000, _loaded([event]))


def test_archive_writer_uses_valid_json_and_atomic_destination(tmp_path):
    events = [_event(1)]
    document = build_archive_document("BTCUSDT", START_MS, START_MS + 10_000, _loaded(events))
    target = write_archive_atomic(tmp_path / "exports" / "btc.json", document)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["manifest"]["coverage_is_complete"] is False
    assert saved["events"][0]["payload"]["m"] is False
    assert list(target.parent.glob("*.tmp")) == []
    with pytest.raises(OrderFlowArchiveExportError, match="already exists"):
        write_archive_atomic(target, document)

def test_archive_writer_does_not_overwrite_destination_created_during_publish(tmp_path, monkeypatch):
    events = [_event(1)]
    document = build_archive_document("BTCUSDT", START_MS, START_MS + 10_000, _loaded(events))
    target = tmp_path / "exports" / "btc.json"
    real_link = archive_export.os.link

    def create_competing_destination(source, destination):
        Path(destination).write_text("keep existing archive", encoding="utf-8")
        return real_link(source, destination)

    monkeypatch.setattr(archive_export.os, "link", create_competing_destination)
    with pytest.raises(OrderFlowArchiveExportError, match="already exists"):
        write_archive_atomic(target, document)

    assert target.read_text(encoding="utf-8") == "keep existing archive"
    assert list(target.parent.glob("*.tmp")) == []


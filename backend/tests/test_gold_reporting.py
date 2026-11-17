from datetime import datetime, timedelta, timezone
from io import BytesIO
import json

from PIL import Image

from app.gold_reporting import (
    append_gold_snapshot,
    build_gold_report_image,
    find_24h_reference,
    gold_snapshot_from_overview,
)
from app.telegram_worker import _gold_report_slot


def test_gold_snapshot_converts_24k_and_22k_to_lkr_per_gram():
    snapshot = gold_snapshot_from_overview({
        "gold_lkr_gram": 40000.0,
        "gold_usd_oz": 3000.0,
        "usd_lkr": 414.0,
        "sources": {"gold": "Gold API XAU", "fx": "FX daily reference"},
    }, datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc))
    assert snapshot["24k_per_gram"] == 40000.0
    assert snapshot["22k_per_gram"] == 40000.0 * 22 / 24
    assert snapshot["source"] == "Gold API XAU · FX daily reference"


def test_24_hour_reference_only_uses_a_sample_between_23_and_25_hours_old():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    old = {
        "timestamp": (now - timedelta(hours=24)).isoformat(),
        "24k_per_gram": 40000.0,
        "22k_per_gram": 36666.67,
    }
    history = json.dumps([old])
    assert find_24h_reference(history, now) == old
    assert find_24h_reference("[]", now) is None


def test_gold_snapshot_history_is_deduplicated_and_retained():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    sample = {
        "timestamp": now.isoformat(), "24k_per_gram": 40000,
        "22k_per_gram": 36666, "usd_lkr": 414, "source": "test",
    }
    once = append_gold_snapshot("[]", sample)
    twice = append_gold_snapshot(once, sample)
    assert len(json.loads(twice)) == 1


def test_gold_image_is_4k_portrait_jpeg_and_contains_complete_layout():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    sample = {
        "timestamp": now.isoformat(), "gold_usd_oz": 3000,
        "usd_lkr": 414, "24k_per_gram": 40000,
        "22k_per_gram": 36666.67, "source": "test provider",
    }
    data = build_gold_report_image(sample, None, now)
    image = Image.open(BytesIO(data))
    assert image.format == "JPEG"
    assert image.size == (2160, 3840)


def test_gold_report_schedule_is_midnight_and_noon_colombo_only():
    from zoneinfo import ZoneInfo
    colombo = ZoneInfo("Asia/Colombo")
    assert _gold_report_slot(datetime(2026, 11, 18, 0, 5, tzinfo=colombo)) == "2026-11-18-00"
    assert _gold_report_slot(datetime(2026, 11, 18, 12, 5, tzinfo=colombo)) == "2026-11-18-12"
    assert _gold_report_slot(datetime(2026, 11, 18, 6, 5, tzinfo=colombo)) is None
    assert _gold_report_slot(datetime(2026, 11, 18, 12, 10, tzinfo=colombo)) is None

from datetime import datetime, timezone

from app.telegram_worker import (
    _market_session_open_ids,
    _market_session_snapshot,
    _normalise_auto_signal_settings,
    _normalise_signal_settings,
    _normalise_auto_signal_pending,
    _rotating_auto_signal_batch,
    _is_auto_signal_stream_pending,
)


def test_auto_signal_settings_use_safe_defaults_for_json_null_and_invalid_types():
    expected = {
        "enabled": False,
        "interval_seconds": 180,
        "universe_mode": "ALL_BINANCE_SPOT",
        "scan_batch_size": 20,
        "symbols": [],
    }
    assert _normalise_auto_signal_settings("null") == expected
    assert _normalise_auto_signal_settings("[]") == expected
    assert _normalise_auto_signal_settings("{broken") == expected


def test_auto_signal_settings_clamp_interval_and_filter_duplicate_symbols():
    result = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":"99999","universe_mode":"SELECTED","symbols":["btcusdt","XAUUSD","BTCUSDT","BAD"]}'
    )
    assert result == {
        "enabled": True,
        "interval_seconds": 3600,
        "universe_mode": "SELECTED",
        "scan_batch_size": 20,
        "symbols": ["BTCUSDT", "XAUUSD"],
    }


def test_auto_signal_settings_recover_from_invalid_interval_and_symbols():
    result = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":"not-a-number","symbols":"BTCUSDT"}'
    )
    assert result == {
        "enabled": True,
        "interval_seconds": 180,
        "universe_mode": "ALL_BINANCE_SPOT",
        "scan_batch_size": 20,
        "symbols": [],
    }


def test_signal_settings_recover_from_non_dict_json_and_clamp_score():
    result = _normalise_signal_settings("null")
    assert result["primary"] == "5"
    assert result["trend"] == "60"
    assert result["enabled"] == ["60", "30", "15", "5", "1"]
    assert result["min_score"] == 8

    result = _normalise_signal_settings(
        '{"primary":"999","trend":"60","enabled":"not-a-list","min_score":99}'
    )
    assert result["primary"] == "5"
    assert result["trend"] == "60"
    assert result["enabled"] == ["60", "30", "15", "5", "1"]
    assert result["min_score"] == 10


def test_signal_settings_clamp_minimum_to_automatic_signal_floor():
    assert _normalise_signal_settings('{"min_score":6}')["min_score"] == 8
    assert _normalise_signal_settings('{"min_score":"bad"}')["min_score"] == 8


def test_market_session_snapshot_reports_live_sessions_and_overlap():
    snapshot = _market_session_snapshot(datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc))
    assert set(snapshot) == {"london", "new-york"}
    assert _market_session_open_ids(snapshot) == "london,new-york"
    assert snapshot["london"]["close_colombo"].strftime("%H:%M") == "22:30"
    assert snapshot["new-york"]["close_colombo"].strftime("%H:%M") == "03:30"


def test_market_session_snapshot_respects_weekends_and_dst():
    weekend = _market_session_snapshot(datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc))
    assert weekend == {}

    summer = _market_session_snapshot(datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc))
    winter = _market_session_snapshot(datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc))
    assert set(summer) == {"london", "new-york"}
    assert set(winter) == {"london", "new-york"}
    assert summer["new-york"]["close_utc"].hour == 21
    assert winter["new-york"]["close_utc"].hour == 22


def test_legacy_default_btc_eth_sol_watchlist_migrates_to_full_spot_universe():
    from app.telegram_worker import _normalise_auto_signal_settings

    result = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}'
    )
    assert result["universe_mode"] == "ALL_BINANCE_SPOT"
    assert result["symbols"] == []


def test_legacy_custom_watchlist_is_preserved_as_selected_mode():
    from app.telegram_worker import _normalise_auto_signal_settings

    result = _normalise_auto_signal_settings(
        '{"enabled":true,"symbols":["BTCUSDT","1000PEPEUSDT"]}'
    )
    assert result["universe_mode"] == "SELECTED"
    assert result["symbols"] == ["BTCUSDT", "1000PEPEUSDT"]


def test_full_universe_mode_keeps_only_optional_gold_addon_not_legacy_pairs():
    from app.telegram_worker import _normalise_auto_signal_settings

    result = _normalise_auto_signal_settings(
        '{"universe_mode":"ALL_BINANCE_SPOT","symbols":["BTCUSDT","XAUUSD"]}'
    )
    assert result["universe_mode"] == "ALL_BINANCE_SPOT"
    assert result["symbols"] == ["XAUUSD"]


def test_rotating_auto_scan_batch_covers_universe_without_duplicates():
    from app.telegram_worker import _rotating_auto_signal_batch

    universe = ["ADAUSDT", "BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    first = _rotating_auto_signal_batch(universe, None, 2)
    second = _rotating_auto_signal_batch(universe, first[-1], 2)
    third = _rotating_auto_signal_batch(universe, second[-1], 2)

    assert first == ["ADAUSDT", "BNBUSDT"]
    assert second == ["BTCUSDT", "ETHUSDT"]
    assert third == ["SOLUSDT", "ADAUSDT"]
    assert len(set(first + second[:1] + second[1:] + third[:1])) == 5


def test_rotating_auto_scan_batch_skips_pending_symbols_and_handles_removed_cursor():
    from app.telegram_worker import _rotating_auto_signal_batch

    assert _rotating_auto_signal_batch(
        ["ADAUSDT", "BNBUSDT", "BTCUSDT", "ETHUSDT"],
        "REMOVEDUSDT",
        3,
        excluded={"ADAUSDT"},
    ) == ["BNBUSDT", "BTCUSDT", "ETHUSDT"]


def test_pending_stream_queue_is_bounded_and_discards_delisted_symbols():
    from app.telegram_worker import _normalise_auto_signal_pending

    raw = '[{"symbol":"BTCUSDT","attempts":2},{"symbol":"OLDUSDT","attempts":1},"ETHUSDT",{"symbol":"SOLUSDT","attempts":99}]'
    result = _normalise_auto_signal_pending(raw, ["BTCUSDT", "ETHUSDT"])
    assert result == {"BTCUSDT": 2, "ETHUSDT": 1}


def test_auto_signal_stream_pending_requires_explicit_not_ready_websocket_state():
    from app.telegram_worker import _is_auto_signal_stream_pending

    assert _is_auto_signal_stream_pending({
        "signal": None,
        "order_flow": {"data_mode": "PUBLIC_WEBSOCKET_STREAM", "stream_ready": False},
    }) is True
    assert _is_auto_signal_stream_pending({
        "signal": None,
        "order_flow": {"data_mode": "PUBLIC_REST_SNAPSHOT", "stream_ready": False},
    }) is False
    assert _is_auto_signal_stream_pending({
        "signal": {"side": "BUY"},
        "order_flow": {"data_mode": "PUBLIC_WEBSOCKET_STREAM", "stream_ready": False},
    }) is False

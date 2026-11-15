from app.telegram_worker import _normalise_auto_signal_settings, _normalise_signal_settings


def test_auto_signal_settings_use_safe_defaults_for_json_null_and_invalid_types():
    expected = {
        "enabled": False,
        "interval_seconds": 180,
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    }
    assert _normalise_auto_signal_settings("null") == expected
    assert _normalise_auto_signal_settings("[]") == expected
    assert _normalise_auto_signal_settings("{broken") == expected


def test_auto_signal_settings_clamp_interval_and_filter_duplicate_symbols():
    result = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":"99999","symbols":["btcusdt","XAUUSD","BTCUSDT","BAD"]}'
    )
    assert result == {
        "enabled": True,
        "interval_seconds": 3600,
        "symbols": ["BTCUSDT", "XAUUSD"],
    }


def test_auto_signal_settings_recover_from_invalid_interval_and_symbols():
    result = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":"not-a-number","symbols":"BTCUSDT"}'
    )
    assert result == {
        "enabled": True,
        "interval_seconds": 180,
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

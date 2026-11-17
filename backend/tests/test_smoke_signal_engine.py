from __future__ import annotations

import asyncio

import pytest

from smoke_signal_engine import _run, rotating_symbol_sample


def test_rotating_sample_is_deterministic_unique_and_covers_each_pair():
    universe = [f"COIN{index:03d}USDT" for index in range(24)]
    day_zero = rotating_symbol_sample(universe, 8, day_index=0)
    day_one = rotating_symbol_sample(universe, 8, day_index=1)
    day_two = rotating_symbol_sample(universe, 8, day_index=2)

    assert day_zero == rotating_symbol_sample(list(reversed(universe)), 8, day_index=0)
    assert len(day_zero) == 8
    assert len(set(day_zero)) == 8
    assert day_zero != day_one != day_two
    assert set(day_zero + day_one + day_two) == set(universe)


def test_rotating_sample_handles_small_universe_and_invalid_size():
    assert rotating_symbol_sample(["ETHUSDT", "BTCUSDT"], 20, day_index=0) == [
        "BTCUSDT", "ETHUSDT"
    ]
    assert rotating_symbol_sample([], 20, day_index=0) == []
    with pytest.raises(ValueError, match="positive integer"):
        rotating_symbol_sample(["BTCUSDT"], 0, day_index=0)


def test_smoke_run_scans_dynamic_sample_without_hardcoded_symbols(monkeypatch):
    import smoke_signal_engine as smoke

    universe = [f"COIN{index:03d}USDT" for index in range(12)]
    calls = []

    async def fake_universe():
        return universe

    async def fake_build(settings, symbol):
        calls.append(symbol)
        return {
            "provider": "Mocked Binance Spot",
            "signal": None,
            "confluence_score": 0,
        }

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_build)
    result = asyncio.run(_run(None, 8, universe_sample_size=4, sample_day=0))

    assert result == 0
    assert calls == rotating_symbol_sample(universe, 4, day_index=0)

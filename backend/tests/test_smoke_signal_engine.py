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


def test_smoke_run_scans_dynamic_sample_without_hardcoded_symbols(monkeypatch, capsys):
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
            "order_flow": {
                "status": "CONTRADICTED",
                "accepted": False,
                "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
                "stream_ready": True,
                "trade_count": 18,
                "delta": -3.5,
                "delta_ratio": -0.25,
                "cvd_value": 24.0,
                "cvd_status": "COMPLETE_SINCE_STATE_SEED",
                "session_delta": 11.5,
                "trade_data_age_seconds": 0.7,
                "session_delta_coverage_complete": False,
                "order_book": {"spread_bps": 2.1, "depth_imbalance": -0.14},
                "data_sources": {"stream": "wss://must-not-be-dumped.example"},
            },
        }

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_build)
    result = asyncio.run(_run(None, 8, universe_sample_size=4, sample_day=0))

    output = capsys.readouterr().out
    assert result == 0
    assert calls == rotating_symbol_sample(universe, 4, day_index=0)
    assert "Order Flow: status=CONTRADICTED | accepted=no" in output
    assert "delta=-3.5" in output
    assert "cvd_value=24" in output
    assert "session_delta=11.5" in output
    assert "spread_bps=2.1" in output
    assert "wss://" not in output


def test_smoke_run_skips_new_pairs_without_enough_closed_history(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    async def fake_universe():
        return ["NEWUSDT", "BTCUSDT"]

    async def fake_build(settings, symbol):
        if symbol == "NEWUSDT":
            raise smoke.MarketDataError("Not enough CLOSED NEWUSDT 5min Binance candles (80 received).")
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_build)
    result = asyncio.run(_run(None, 8, universe_sample_size=2, sample_day=0))

    output = capsys.readouterr().out
    assert result == 0
    assert "[SKIP] NEWUSDT" in output
    assert "1 insufficient-history skip(s)" in output


def test_order_flow_diagnostic_formatter_handles_missing_and_non_finite_values():
    from smoke_signal_engine import _format_order_flow_diagnostics

    assert _format_order_flow_diagnostics({}) == "  Order Flow: UNAVAILABLE"
    line = _format_order_flow_diagnostics({
        "order_flow": {
            "status": "NOT_EVALUATED_NO_DIRECTIONAL_SETUP",
            "accepted": None,
            "delta": float("nan"),
            "order_book": {"spread_bps": float("inf")},
        }
    })
    assert "status=NOT_EVALUATED_NO_DIRECTIONAL_SETUP" in line
    assert "accepted=n/a" in line
    assert "delta=" not in line
    assert "spread_bps=" not in line

def test_smoke_run_scans_dynamic_usdm_perpetual_sample_separately(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    spot_symbols = ["BTCUSDT", "ETHUSDT"]
    futures_symbols = [f"PERP{index:03d}USDT" for index in range(11)]
    spot_calls = []
    futures_calls = []

    async def fake_spot_universe():
        return spot_symbols

    async def fake_spot_build(settings, symbol):
        spot_calls.append(symbol)
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def fake_usdm_universe():
        return futures_symbols

    async def fake_usdm_analyze(symbol, interval, min_score):
        futures_calls.append((symbol, interval, min_score))
        return {
            "market_type": "BINANCE_USDM_FUTURES",
            "status": "WAIT",
            "signal": None,
            "confluence_score": 0,
            "message": "WAIT — no qualifying closed-candle setup.",
            "execution_enabled": False,
            "order_flow_enabled": False,
        }

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_spot_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_spot_build)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", fake_usdm_universe)
    monkeypatch.setattr(smoke, "analyze_usdm_futures_signal", fake_usdm_analyze)

    result = asyncio.run(_run(
        None, 8,
        universe_sample_size=2,
        sample_day=1,
        include_usdm=True,
        usdm_universe_sample_size=3,
    ))

    expected = rotating_symbol_sample(futures_symbols, 3, day_index=1)
    output = capsys.readouterr().out
    assert result == 0
    assert spot_calls == spot_symbols
    assert [call[0] for call in futures_calls] == expected
    assert all(call[1] == "5m" and call[2] == 8 for call in futures_calls)
    assert "Eligible TRADING PERPETUAL contracts from exchangeInfo: 11" in output
    assert "Futures scope: closed 5m candles only" in output
    assert "[FUTURES WAIT]" in output
    assert "Execution: DISABLED | Order Flow: NOT AVAILABLE" in output
    assert "Neither sample means every eligible contract was scanned" in output


def test_usdm_smoke_counts_new_contracts_without_history_as_skips(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    async def fake_spot_universe():
        return ["BTCUSDT"]

    async def fake_spot_build(*_args):
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def fake_usdm_universe():
        return ["NEWUSDT"]

    async def fake_usdm_analyze(*_args):
        raise smoke.BinanceUsdMSignalError(
            "At least 210 fully closed 5m USDⓈ-M candles are required; received 80."
        )

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_spot_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_spot_build)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", fake_usdm_universe)
    monkeypatch.setattr(smoke, "analyze_usdm_futures_signal", fake_usdm_analyze)

    result = asyncio.run(_run(
        None, 8,
        universe_sample_size=1,
        sample_day=0,
        include_usdm=True,
        usdm_universe_sample_size=1,
    ))

    output = capsys.readouterr().out
    assert result == 0
    assert "[FUTURES SKIP] NEWUSDT.P" in output
    assert "1 insufficient-history skip(s)" in output

def test_usdm_smoke_runs_even_when_spot_exchange_info_is_unavailable(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    calls = []

    async def fail_spot_universe():
        raise smoke.MarketDataError("Binance Spot exchangeInfo unavailable")

    async def fake_usdm_universe():
        return ["BTCUSDT"]

    async def fake_usdm_analyze(symbol, interval, min_score):
        calls.append((symbol, interval, min_score))
        return {
            "market_type": "BINANCE_USDM_FUTURES",
            "status": "WAIT",
            "signal": None,
            "confluence_score": 0,
            "message": "No qualifying Futures setup.",
        }

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fail_spot_universe)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", fake_usdm_universe)
    monkeypatch.setattr(smoke, "analyze_usdm_futures_signal", fake_usdm_analyze)

    result = asyncio.run(_run(
        None, 8,
        include_usdm=True,
        usdm_universe_sample_size=1,
        sample_day=0,
    ))

    output = capsys.readouterr().out
    assert result == 1  # Spot provider failure remains visible to CI.
    assert calls == [("BTCUSDT", "5m", 8)]
    assert "Binance Spot symbol discovery failed" in output
    assert "[FUTURES WAIT] BTCUSDT.P" in output
    assert "1 provider/error failure(s)" in output


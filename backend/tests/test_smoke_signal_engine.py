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
            "message": "WAIT — confluence score is below threshold.",
            "wait_reasons": ["Confluence score is below threshold."],
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
    assert "reason=WAIT — confluence score is below threshold." in output
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

    async def fake_usdm_analyze(*_args, **_kwargs):
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

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert result == 1  # Spot provider failure remains visible to CI.
    assert calls == [("BTCUSDT", "5m", 8)]
    assert "Binance Spot symbol discovery failed" in output
    assert "[FUTURES WAIT] BTCUSDT.P" in output
    assert "1 provider/error failure(s)" in output



def test_usdm_http_451_is_reported_as_unavailable_without_failing_spot_smoke(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    spot_calls = []

    async def fake_spot_universe():
        return ["BTCUSDT"]

    async def fake_spot_build(_settings, symbol):
        spot_calls.append(symbol)
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def blocked_usdm_universe():
        raise smoke.BinanceUsdMDataError("exchangeInfo unavailable (451)", status_code=451)

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_spot_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_spot_build)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", blocked_usdm_universe)

    result = asyncio.run(_run(
        None, 8, universe_sample_size=1, sample_day=0,
        include_usdm=True, usdm_universe_sample_size=1,
    ))

    output = capsys.readouterr().out
    assert result == 0
    assert spot_calls == ["BTCUSDT"]
    assert "[FUTURES UNAVAILABLE]" in output
    assert "HTTP 451" in output
    assert "not a WAIT" in output
    assert "0 provider/error failure(s)" in output


def test_usdm_http_429_remains_a_provider_failure(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    async def fake_spot_universe():
        return ["BTCUSDT"]

    async def fake_spot_build(*_args):
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def rate_limited_usdm_universe():
        raise smoke.BinanceUsdMDataError("rate limited (429)", status_code=429)

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_spot_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_spot_build)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", rate_limited_usdm_universe)

    result = asyncio.run(_run(
        None, 8, universe_sample_size=1, sample_day=0,
        include_usdm=True, usdm_universe_sample_size=1,
    ))

    output = capsys.readouterr().err
    assert result == 1
    assert "symbol discovery failed" in output
    assert "429" in output



def test_usdm_http_451_during_candle_scan_stops_remaining_futures_pairs(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    futures_calls = []

    async def fake_spot_universe():
        return ["BTCUSDT"]

    async def fake_spot_build(*_args):
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def fake_usdm_universe():
        return ["BTCUSDT", "ETHUSDT"]

    async def blocked_candles(symbol, *_args, **_kwargs):
        futures_calls.append(symbol)
        raise smoke.BinanceUsdMSignalError("candle provider blocked (451)", status_code=451)

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_spot_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_spot_build)
    monkeypatch.setattr(smoke, "get_binance_usdm_symbols", fake_usdm_universe)
    monkeypatch.setattr(smoke, "analyze_usdm_futures_signal", blocked_candles)

    result = asyncio.run(_run(
        None, 8, universe_sample_size=1, sample_day=0,
        include_usdm=True, usdm_universe_sample_size=2,
    ))

    output = capsys.readouterr().out
    assert result == 0
    assert futures_calls == ["BTCUSDT"]
    assert "[FUTURES UNAVAILABLE]" in output
    assert "during candle retrieval" in output
    assert "coverage is incomplete" in output
    assert "0 provider/error failure(s)" in output


def test_order_flow_probe_selects_highest_volume_eligible_usdt_pair_dynamically():
    from smoke_signal_engine import select_order_flow_probe_symbols

    universe = ["AAAUSDT", "BTCUSDT", "ETHUSDT", "BTCUSDC"]
    tickers = [
        {"symbol": "AAAUSDT", "quoteVolume": "150"},
        {"symbol": "BTCUSDT", "quoteVolume": "900000"},
        {"symbol": "ETHUSDT", "quoteVolume": "400000"},
        {"symbol": "BTCUSDC", "quoteVolume": "999999999"},
        {"symbol": "DELISTEDUSDT", "quoteVolume": "999999999"},
        {"symbol": "AAAUSDT", "quoteVolume": "nan"},
        {"symbol": "BADUSDT", "quoteVolume": "inf"},
    ]

    assert select_order_flow_probe_symbols(universe, tickers, limit=2) == [
        "BTCUSDT", "ETHUSDT"
    ]


def test_order_flow_probe_rejects_invalid_selection_inputs():
    from smoke_signal_engine import select_order_flow_probe_symbols

    with pytest.raises(ValueError, match="positive integer"):
        select_order_flow_probe_symbols(["BTCUSDT"], [], limit=0)
    with pytest.raises(ValueError, match="must be a list"):
        select_order_flow_probe_symbols(["BTCUSDT"], {})


def test_live_order_flow_probe_requires_public_trade_and_sequence_validated_depth(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    class FakeManager:
        def __init__(self):
            self.stopped = False
            self.request = None

        async def get_snapshot(self, symbol, tick_size, *, wait_seconds):
            self.request = (symbol, tick_size, wait_seconds)
            return {
                "market_type": "BINANCE_SPOT",
                "status": "LIVE",
                "signal_ready": True,
                "order_flow": {
                    "feed_mode": "PUBLIC_WEBSOCKET_STREAM",
                    "depth_is_continuous": True,
                    "trade_count": 42,
                    "delta_ratio": 0.35,
                    "cvd_value": 7.5,
                    "cvd_scope": "SINCE_STATE_SEED",
                    "order_book": {"spread_bps": 1.2, "depth_imbalance": 0.18},
                    "data_provenance": {"candle_volume_used": False},
                },
            }

        async def stop(self):
            self.stopped = True

    manager = FakeManager()
    async def fake_select(_universe, *, limit):
        assert limit == 1
        return ["BTCUSDT"]

    async def fake_symbol_info(symbol):
        assert symbol == "BTCUSDT"
        return {"filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}

    monkeypatch.setattr(smoke, "_load_spot_order_flow_probe_symbols", fake_select)
    monkeypatch.setattr(smoke, "get_binance_spot_symbol_info", fake_symbol_info)
    monkeypatch.setattr(
        smoke, "get_binance_spot_order_flow_manager", lambda: manager,
        raising=False,
    )

    ready, failures = asyncio.run(
        smoke._run_spot_order_flow_probe(["BTCUSDT", "ETHUSDT"], wait_seconds=6)
    )

    output = capsys.readouterr().out
    assert (ready, failures) == (1, 0)
    assert manager.request == ("BTCUSDT", "0.01", 6.0)
    assert manager.stopped is True
    assert "[ORDER FLOW READY] BTCUSDT" in output
    assert "cvd_scope=SINCE_STATE_SEED" in output


def test_live_order_flow_probe_reports_bootstrap_as_not_ready_not_as_signal_wait(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    class FakeManager:
        stopped = False

        async def get_snapshot(self, *_args, **_kwargs):
            return {
                "market_type": "BINANCE_SPOT",
                "status": "DEPTH_BRIDGING",
                "signal_ready": False,
                "order_flow": None,
                "last_error": "waiting for a post-snapshot depth update",
            }

        async def stop(self):
            self.stopped = True

    manager = FakeManager()
    async def fake_select(_universe, *, limit):
        return ["ETHUSDT"]

    async def fake_symbol_info(_symbol):
        return {"filters": {"PRICE_FILTER": {"tickSize": "0.01"}}}

    monkeypatch.setattr(smoke, "_load_spot_order_flow_probe_symbols", fake_select)
    monkeypatch.setattr(smoke, "get_binance_spot_symbol_info", fake_symbol_info)
    monkeypatch.setattr(smoke, "get_binance_spot_order_flow_manager", lambda: manager, raising=False)

    ready, failures = asyncio.run(smoke._run_spot_order_flow_probe(["ETHUSDT"], wait_seconds=2))
    output = capsys.readouterr().out

    assert (ready, failures) == (0, 1)
    assert manager.stopped is True
    assert "[ORDER FLOW NOT READY] ETHUSDT" in output
    assert "DEPTH_BRIDGING" in output
    assert "waiting for a post-snapshot depth update" in output
    assert "WAIT" not in output


def test_smoke_exit_status_includes_independent_order_flow_probe_failures(monkeypatch, capsys):
    import smoke_signal_engine as smoke

    async def fake_universe():
        return ["BTCUSDT"]

    async def fake_build(_settings, _symbol):
        return {"provider": "Binance Spot", "signal": None, "confluence_score": 0}

    async def fake_probe(_universe, *, wait_seconds):
        assert wait_seconds == 4
        return 0, 1

    monkeypatch.setattr(smoke, "get_binance_spot_symbols", fake_universe)
    monkeypatch.setattr(smoke, "build_signal", fake_build)
    monkeypatch.setattr(smoke, "_run_spot_order_flow_probe", fake_probe)

    result = asyncio.run(_run(
        None, 8, universe_sample_size=1, sample_day=0,
        include_order_flow_probe=True, order_flow_probe_wait_seconds=4,
    ))
    output = capsys.readouterr().out

    assert result == 1
    assert "0 ready Spot Order Flow probe(s)" in output
    assert "1 Order Flow probe failure(s)" in output

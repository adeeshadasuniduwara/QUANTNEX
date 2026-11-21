from datetime import datetime, timedelta, timezone
import asyncio

import pytest

from app import binance_usdm_signal_engine as engine


def candles(count=220, age_seconds=60):
    now = datetime.now(timezone.utc)
    interval_seconds = engine.INTERVAL_SECONDS["15m"]
    last_stamp = now - timedelta(seconds=age_seconds)
    start = last_stamp - timedelta(seconds=interval_seconds * (count - 1))
    rows = []
    for index in range(count):
        stamp = start + timedelta(seconds=interval_seconds * index)
        price = 100 + index * 0.1
        rows.append({
            "time": stamp.isoformat(), "open": price - 0.02,
            "high": price + 0.10, "low": price - 0.10,
            "close": price, "volume": 100.0,
        })
    return rows


def test_futures_engine_uses_only_validated_usdm_candles_and_marks_read_only(monkeypatch):
    rows = candles()
    async def fake_fetch(symbol, interval, limit):
        assert (symbol, interval, limit) == ("BTCUSDT", "15m", 1000)
        return rows
    monkeypatch.setattr(engine, "fetch_binance_usdm_candles", fake_fetch)
    from app import quantnex_view_intelligence
    def fake_analyze(candle_rows, symbol, interval, min_score):
        return {"symbol": symbol, "interval": interval, "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "SIGNAL", "signal": {"symbol": symbol, "side": "BUY", "entry": 100,
                "stop_loss": 99, "tp1": 101, "tp2": 102, "tp3": 103, "score": 8},
                "confluence_score": 8, "score_out_of": 20, "eligible_setups": 2}
    monkeypatch.setattr(quantnex_view_intelligence, "analyze_candles", fake_analyze)
    result = asyncio.run(engine.analyze_usdm_futures_signal("btcusdt", "15m", 6))
    assert result["market_type"] == "BINANCE_USDM_FUTURES"
    assert result["provider"] == "Binance USDⓈ-M Futures"
    assert result["signal_engine"] == "QUANTNEX_USDM_CANDLE_CONFLUENCE_V1"
    assert result["signal"]["symbol"] == "BTCUSDT.P"
    assert result["signal"]["exchange_symbol"] == "BTCUSDT"
    assert result["execution_enabled"] is False
    assert result["order_flow_enabled"] is False


@pytest.mark.parametrize("symbol,interval,min_score", [
    ("BTC-USDT", "15m", 6), ("BTCUSDT", "2m", 6), ("BTCUSDT", "15m", 3),
])
def test_futures_engine_rejects_invalid_inputs(symbol, interval, min_score):
    with pytest.raises(engine.BinanceUsdMSignalError):
        asyncio.run(engine.analyze_usdm_futures_signal(symbol, interval, min_score))


def test_futures_engine_fails_closed_on_short_history(monkeypatch):
    async def fake_fetch(*_args):
        return candles(100)
    monkeypatch.setattr(engine, "fetch_binance_usdm_candles", fake_fetch)
    with pytest.raises(engine.BinanceUsdMSignalError, match="210"):
        asyncio.run(engine.analyze_usdm_futures_signal("BTCUSDT", "15m", 6))


def test_futures_engine_fails_closed_on_stale_history(monkeypatch):
    async def fake_fetch(*_args):
        return candles(220, age_seconds=4000)
    monkeypatch.setattr(engine, "fetch_binance_usdm_candles", fake_fetch)
    with pytest.raises(engine.BinanceUsdMSignalError, match="stale"):
        asyncio.run(engine.analyze_usdm_futures_signal("BTCUSDT", "15m", 6))


def test_futures_engine_rejects_non_chronological_or_malformed_candles(monkeypatch):
    rows = candles()
    rows[-1]["time"] = rows[-2]["time"]
    async def fake_fetch(*_args):
        return rows
    monkeypatch.setattr(engine, "fetch_binance_usdm_candles", fake_fetch)
    with pytest.raises(engine.BinanceUsdMSignalError, match="validation"):
        asyncio.run(engine.analyze_usdm_futures_signal("BTCUSDT", "15m", 6))

from datetime import datetime, timezone, timedelta
import pytest
from app.phase10_engine import assess_quote, assess_candles, assess_market_snapshot, execution_gate

NOW=datetime(2026,11,12,12,0,tzinfo=timezone.utc)

def quote(stamp,kind="crypto",price=100):
    return {"symbol":"BTCUSDT","provider":"test","kind":kind,"price":price,"source_timestamp":stamp}

def test_fresh_provider_quote_is_healthy():
    r=assess_quote(quote(NOW.isoformat()),NOW)
    assert r["status"]=="HEALTHY" and r["trading_safe"]

def test_missing_timestamp_blocks_execution():
    r=execution_gate(quote(None),NOW)
    assert not r["allowed"]
    assert "MISSING_PROVIDER_TIMESTAMP" in r["health"]["issues"]

def test_stale_crypto_quote_is_unsafe():
    r=assess_quote(quote((NOW-timedelta(minutes=5)).isoformat()),NOW)
    assert r["status"]=="UNSAFE" and "STALE_QUOTE" in r["issues"]

def test_fx_quote_uses_separate_staleness_window():
    r=assess_quote(quote((NOW-timedelta(minutes=10)).isoformat(),"forex"),NOW)
    assert r["trading_safe"]

def test_invalid_and_future_prices_are_rejected():
    assert "INVALID_PRICE" in assess_quote(quote(NOW.isoformat(),price=float("nan")),NOW)["issues"]
    assert "FUTURE_PROVIDER_TIMESTAMP" in assess_quote(quote((NOW+timedelta(minutes=2)).isoformat()),NOW)["issues"]

def candles(start,count=4,step=900):
    return [{"time":(start+timedelta(seconds=i*step)).isoformat(),"open":100,"high":102,
             "low":99,"close":101,"volume":1} for i in range(count)]

def test_valid_candles_are_healthy():
    rows=candles(NOW-timedelta(hours=1))
    assert assess_candles(rows,"15m",NOW)["status"]=="HEALTHY"

def test_duplicate_and_non_monotonic_candles_are_unsafe():
    rows=candles(NOW-timedelta(hours=1))
    rows[2]=dict(rows[1])
    result=assess_candles(rows,"15m",NOW)
    assert not result["trading_safe"]
    assert "DUPLICATE_CANDLE" in result["issues"]

def test_invalid_ohlc_is_unsafe():
    rows=candles(NOW-timedelta(hours=1))
    rows[1]["high"]=98
    assert "INVALID_OHLC_RANGE" in assess_candles(rows,"15m",NOW)["issues"]

def test_large_gap_is_reported_as_degraded():
    rows=candles(NOW-timedelta(hours=2),3,step=3600)
    result=assess_candles(rows,"15m",NOW)
    assert result["status"]=="DEGRADED"
    assert "CANDLE_TIME_GAPS" in result["warnings"]

def test_empty_candle_series_blocks():
    assert not assess_candles([],"15m",NOW)["trading_safe"]

def test_combined_snapshot_blocks_if_either_feed_is_unsafe():
    q=quote((NOW-timedelta(minutes=5)).isoformat())
    result=assess_market_snapshot(q,candles(NOW-timedelta(hours=1)),"15m",NOW)
    assert result["status"]=="UNSAFE"

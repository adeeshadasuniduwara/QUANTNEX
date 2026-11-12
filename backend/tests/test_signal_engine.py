from datetime import datetime, timezone, timedelta
from app.signal_engine import aggregate_minutes, ema, rsi, atr, adx, macd, inspect_tf

def candles(count=320):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[]
    price=2000.0
    for i in range(count):
        price += 0.08
        rows.append({"time":(start+timedelta(minutes=i)).isoformat(),"open":price-0.03,
                     "high":price+0.12,"low":price-0.10,"close":price})
    return rows

def test_indicator_functions_return_finite_values():
    rows=candles()
    closes=[x["close"] for x in rows]
    assert len(ema(closes,20))==len(closes)
    assert 0<=rsi(closes)<=100
    assert atr(rows)>0
    assert adx(rows)>=0
    line,signal,hist=macd(closes)
    assert all(map(lambda x: isinstance(x,float),(line,signal,hist)))

def test_timeframe_aggregation_and_snapshot():
    rows=candles(320)
    aggregated=aggregate_minutes(rows,50)
    assert len(aggregated)==7
    snapshot=inspect_tf(rows)
    assert snapshot["bias"]=="BULLISH"
    assert snapshot["ema20"]>snapshot["ema50"]
    assert snapshot["structure"]["swing_high"]>snapshot["structure"]["swing_low"]


def test_lkr_gold_price_conversion_uses_troy_ounce_and_gram():
    from app.market_data import gold_lkr_per_gram
    per_gram = gold_lkr_per_gram(3000.0, 300.0)
    assert round(per_gram, 2) == round((3000.0 / 31.1034768) * 300.0, 2)
    assert round(per_gram * 8, 2) == round((3000.0 / 31.1034768) * 300.0 * 8, 2)


def test_binance_crypto_candles_use_public_klines(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    payload = []
    for index in range(220):
        price = 42000.0 + index
        payload.append([start + index * 900000, str(price), str(price + 5), str(price - 5),
                        str(price + 1), "12.5", start + (index + 1) * 900000 - 1,
                        "500000", 100, "6.0", "250000", "0"])

    def handler(request):
        assert request.url.host == "api.binance.com"
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["interval"] == "15m"
        return httpx.Response(200, json=payload)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)
    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)

    result = asyncio.run(signal_engine.fetch_candles("15min", 220, "BTCUSDT"))
    assert len(result) == 220
    assert result[0]["open"] == 42000.0
    assert result[-1]["close"] == 42220.0
    assert result[-1]["volume"] == 12.5

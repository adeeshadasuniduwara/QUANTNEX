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



def test_bitcoin_uses_coinbase_candles_when_binance_is_unavailable(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    rows = []
    for index in reversed(range(220)):
        price = 65000.0 + index
        rows.append([start + index * 900, str(price - 2), str(price + 3),
                     str(price), str(price + 1), "0.25"])

    def handler(request):
        if request.url.host == "api.binance.com":
            return httpx.Response(503, json={"msg": "temporarily unavailable"})
        assert request.url.host == "api.exchange.coinbase.com"
        assert request.url.path == "/products/BTC-USD/candles"
        assert request.url.params["granularity"] == "900"
        return httpx.Response(200, json=rows)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)
    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)

    candles, provider = asyncio.run(signal_engine.fetch_candles_with_provider("15min", 220, "BTCUSDT"))
    assert len(candles) == 220
    assert provider == "Coinbase Exchange fallback"
    assert candles[0]["open"] == 65000.0
    assert candles[-1]["close"] == 65220.0


def test_gold_uses_twelve_data_when_enabled_mt5_feed_fails(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine, mt5_feed

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-api-key")
    async def unavailable(*_args, **_kwargs):
        raise mt5_feed.MT5FeedError("demo terminal is not connected")
    monkeypatch.setattr(mt5_feed, "get_candles", unavailable)

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = []
    for index in reversed(range(220)):
        stamp = start + timedelta(minutes=index)
        price = 2300.0 + index * 0.1
        values.append({"datetime": stamp.isoformat(), "open": str(price),
                       "high": str(price + 0.3), "low": str(price - 0.2),
                       "close": str(price + 0.1)})

    def handler(request):
        assert request.url.host == "api.twelvedata.com"
        assert request.url.params["symbol"] == "XAU/USD"
        return httpx.Response(200, json={"values": values})

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)
    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)

    candles, provider = asyncio.run(signal_engine.fetch_candles_with_provider("1min", 220, "XAUUSD"))
    assert len(candles) == 220
    assert provider == "Twelve Data"
    assert candles[-1]["close"] > candles[0]["close"]

def test_telegram_scan_command_supports_crypto_symbols(monkeypatch):
    import asyncio
    from app import telegram_worker

    calls = []
    async def fake_build_signal(settings, symbol):
        calls.append(symbol)
        return {"signal": None, "confluence_score": 4, "score_note": "Rule-based score."}

    class FakeDB:
        def scalar(self, query):
            return None
        def add(self, item):
            raise AssertionError("Crypto WAIT scans must not touch the Gold TP watcher.")
        def commit(self):
            pass

    monkeypatch.setattr(telegram_worker, "build_signal", fake_build_signal)
    response = asyncio.run(telegram_worker._handle_command(None, FakeDB(), 1, "token", "chat", "/scan ETHUSDT"))
    assert calls == ["ETHUSDT"]
    assert "ETHUSDT" in response
    assert "WAIT" in response


def test_telegram_scan_command_defaults_to_bitcoin(monkeypatch):
    import asyncio
    from app import telegram_worker

    calls = []
    async def fake_build_signal(settings, symbol):
        calls.append(symbol)
        return {"signal": None, "confluence_score": 3, "score_note": "Rule-based score."}

    class FakeDB:
        def scalar(self, query):
            return None
        def add(self, item):
            raise AssertionError("Crypto WAIT scans must not touch the Gold TP watcher.")
        def commit(self):
            pass

    monkeypatch.setattr(telegram_worker, "build_signal", fake_build_signal)
    response = asyncio.run(telegram_worker._handle_command(None, FakeDB(), 1, "token", "chat", "/scan"))
    assert calls == ["BTCUSDT"]
    assert "BTCUSDT" in response


def test_structure_exposes_confirmed_event_trend_and_atr_support_resistance_zones():
    from app.signal_engine import structure

    result = structure(candles(320))
    assert result["structure_event"] in {
        "NONE", "BULLISH_BOS", "BEARISH_BOS", "BULLISH_MSS", "BEARISH_MSS"
    }
    assert result["structure_trend"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert result["support_zone"]["low"] < result["support_zone"]["high"]
    assert result["resistance_zone"]["low"] < result["resistance_zone"]["high"]
    assert result["support_zone"]["low"] <= result["swing_low"] <= result["support_zone"]["high"]
    assert result["resistance_zone"]["low"] <= result["swing_high"] <= result["resistance_zone"]["high"]


def test_gold_candle_normalizer_sorts_deduplicates_and_rejects_bad_ohlc():
    from app.signal_engine import _normalize_gold_candles

    rows = [
        {"datetime": "2026-01-01T00:02:00Z", "open": "2", "high": "3", "low": "1", "close": "2.5"},
        {"datetime": "2026-01-01T00:01:00+00:00", "open": "2", "high": "1", "low": "1.5", "close": "2"},
        {"datetime": "2026-01-01T00:02:00+00:00", "open": "2.1", "high": "3.2", "low": "1.1", "close": "2.8"},
        {"datetime": "2026-01-01T00:03:00Z", "open": "nan", "high": "4", "low": "2", "close": "3"},
    ]
    result = _normalize_gold_candles(rows)
    assert len(result) == 1
    assert result[0]["time"] == "2026-01-01T00:02:00+00:00"
    assert result[0]["close"] == 2.8
    assert result[0]["volume"] == 0.0


def test_xauusd_provider_candles_are_cached_and_returned_as_copies(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-api-key")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = []
    for index in reversed(range(220)):
        stamp = start + timedelta(minutes=index)
        price = 2300.0 + index * 0.1
        payload.append({
            "datetime": stamp.isoformat(), "open": str(price),
            "high": str(price + 0.3), "low": str(price - 0.2),
            "close": str(price + 0.1),
        })

    calls = []
    def handler(request):
        calls.append(request.url)
        assert request.url.host == "api.twelvedata.com"
        assert request.url.params["symbol"] == "XAU/USD"
        assert request.url.params["apikey"] == "test-api-key"
        return httpx.Response(200, json={"status": "ok", "values": payload})

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)
    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)

    first = asyncio.run(signal_engine.fetch_candles("1min", 220, "XAUUSD"))
    first[0]["close"] = -1
    second = asyncio.run(signal_engine.fetch_candles("1min", 220, "XAUUSD"))

    assert len(calls) == 1
    assert len(second) == 220
    assert second[0]["time"] < second[-1]["time"]
    assert second[0]["close"] > 0
    assert second[0]["volume"] == 0.0


def test_xauusd_rejects_insufficient_valid_provider_candles(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-api-key")
    payload = [
        {"datetime": f"2026-01-01T00:{index:02d}:00Z", "open": "2300",
         "high": "2299", "low": "2301", "close": "2300"}
        for index in range(10)
    ]

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"values": payload}))
    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)
    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)

    import pytest
    with pytest.raises(signal_engine.MarketDataError, match="Not enough valid"):
        asyncio.run(signal_engine.fetch_candles("1min", 220, "XAUUSD"))

def test_closed_candle_filter_excludes_the_forming_interval():
    from app.signal_engine import closed_candles

    now = datetime(2026, 11, 14, 12, 10, tzinfo=timezone.utc)
    rows = [
        {"time": (now - timedelta(minutes=30)).isoformat(), "close": 1},
        {"time": (now - timedelta(minutes=15)).isoformat(), "close": 2},
        {"time": (now - timedelta(minutes=5)).isoformat(), "close": 3},
    ]
    result = closed_candles(rows, "15min", now)
    assert [row["close"] for row in result] == [1, 2]


def test_binance_signal_fetch_drops_current_unclosed_candle(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    now = datetime.now(timezone.utc)
    last_open = int((now - timedelta(minutes=5)).timestamp() * 1000)
    start = last_open - 219 * 900000
    payload = []
    for index in range(220):
        price = 42000.0 + index
        open_time = start + index * 900000
        payload.append([open_time, str(price), str(price + 5), str(price - 5),
                        str(price + 1), "12.5", open_time + 900000 - 1,
                        "500000", 100, "6.0", "250000", "0"])

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    result, provider = asyncio.run(signal_engine.fetch_candles_with_provider("15min", 220, "BTCUSDT"))
    assert provider == "Binance Spot"
    assert len(result) == 219
    assert result[-1]["time"] == datetime.fromtimestamp((last_open - 900000) / 1000, timezone.utc).isoformat()



def test_gold_feed_provider_accepts_configured_mt5_without_twelve_data(monkeypatch):
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "")
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", True)
    assert signal_engine.gold_feed_configured() is True
    assert signal_engine.gold_feed_provider() == "MetaTrader 5 local terminal"


def test_gold_feed_provider_uses_twelve_data_when_mt5_is_disabled(monkeypatch):
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    assert signal_engine.gold_feed_configured() is True
    assert signal_engine.gold_feed_provider() == "Twelve Data"


def test_gold_feed_provider_is_unavailable_without_either_provider(monkeypatch):
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "")
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    assert signal_engine.gold_feed_configured() is False
    assert signal_engine.gold_feed_provider() is None


def test_candle_freshness_accepts_recent_fully_closed_candle():
    from app.signal_engine import validate_candle_freshness

    now = datetime(2026, 11, 16, 12, 10, tzinfo=timezone.utc)
    rows = [{"time": (now - timedelta(minutes=6)).isoformat()}]
    age = validate_candle_freshness(rows, "5min", now)
    assert age == 60


def test_candle_freshness_rejects_stale_closed_candle():
    import pytest
    from app.signal_engine import MarketDataError, validate_candle_freshness

    now = datetime(2026, 11, 16, 12, 10, tzinfo=timezone.utc)
    rows = [{"time": (now - timedelta(minutes=20)).isoformat()}]
    with pytest.raises(MarketDataError, match="stale"):
        validate_candle_freshness(rows, "5min", now)


def test_candle_freshness_rejects_future_dated_candle():
    import pytest
    from app.signal_engine import MarketDataError, validate_candle_freshness

    now = datetime(2026, 11, 16, 12, 10, tzinfo=timezone.utc)
    rows = [{"time": (now + timedelta(hours=1)).isoformat()}]
    with pytest.raises(MarketDataError, match="future"):
        validate_candle_freshness(rows, "5min", now)


def test_build_signal_rejects_stale_provider_candles(monkeypatch):
    import asyncio
    import pytest
    from app import signal_engine

    stale_rows = candles(320)
    async def stale_provider(_interval, _outputsize, _symbol):
        return stale_rows, "Binance Spot"

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", stale_provider)
    settings = {"primary": "5", "trend": "60", "enabled": ["5", "60"], "min_score": 7}
    with pytest.raises(signal_engine.MarketDataError, match="stale"):
        asyncio.run(signal_engine.build_signal(settings, "BTCUSDT"))


def test_low_price_crypto_signal_levels_keep_required_precision(monkeypatch):
    import asyncio
    from app import signal_engine

    now = datetime.now(timezone.utc)
    def fresh_rows(interval):
        seconds = signal_engine.INTERVAL_SECONDS[interval]
        last_open = now - timedelta(seconds=seconds + 30)
        start = last_open - timedelta(seconds=seconds * 319)
        rows = []
        for index in range(320):
            stamp = start + timedelta(seconds=seconds * index)
            rows.append({"time": stamp.isoformat(), "open": 0.000012,
                         "high": 0.000013, "low": 0.000011, "close": 0.00001234})
        return rows

    async def fake_fetch(interval, _outputsize, _symbol):
        return fresh_rows(interval), "Binance Spot"

    structure = {
        "bos_mss": "BULLISH", "liquidity_sweep": "BULLISH",
        "bullish_fvg": {"low": 0.000012, "high": 0.000013},
        "bullish_order_block": None, "bullish_breaker_block": None, "bullish_ifvg": None,
        "premium_discount": "DISCOUNT", "swing_low": 0.000011, "swing_high": 0.000014,
    }

    def bullish_analysis(_candles):
        return {"bias": "BULLISH", "close": 0.00001234, "ema20": 0.0000122,
                "ema50": 0.0000121, "ema200": 0.0000120, "macd_histogram": 0.0000001,
                "rsi": 55.0, "adx": 25.0, "atr": 0.000001, "structure": structure}

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    settings = {"primary": "5", "trend": "60", "enabled": ["5", "60"], "min_score": 6}
    result = asyncio.run(signal_engine.build_signal(settings, "PEPEUSDT"))
    signal = result["signal"]
    assert signal is not None
    assert 0 < signal["stop_loss"] < signal["entry"] < signal["tp1"] < signal["tp2"] < signal["tp3"]
    assert signal["entry"] > 0.00001
    assert result["timeframes"]["5"]["atr"] > 0


def test_crypto_candle_provider_reports_coinbase_fallback(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    now = datetime.now(timezone.utc)
    last_open = int(now.timestamp() // 900) * 900 - 900
    payload = []
    for index in range(220):
        stamp = last_open - index * 900
        price = 42000.0 + index
        payload.append([stamp, price - 5, price + 5, price, price + 1, 12.5])

    def handler(request):
        if request.url.host == "api.binance.com":
            return httpx.Response(503, json={"msg": "temporary unavailable"})
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=payload)
        raise AssertionError("Unexpected candle provider: " + str(request.url))

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    candles_result, provider = asyncio.run(
        signal_engine.fetch_candles_with_provider("15min", 220, "BTCUSDT")
    )
    assert provider == "Coinbase Exchange fallback"
    assert len(candles_result) == 220
    assert candles_result == sorted(candles_result, key=lambda row: row["time"])


def test_gold_candle_provider_reports_local_mt5(monkeypatch):
    import asyncio
    from app import mt5_feed, signal_engine

    now = datetime.now(timezone.utc)
    seconds = signal_engine.INTERVAL_SECONDS["5min"]
    last_open = now - timedelta(seconds=seconds + 30)
    first_open = last_open - timedelta(seconds=seconds * 209)
    candles = []
    for index in range(210):
        stamp = first_open + timedelta(seconds=seconds * index)
        price = 2300.0 + index * 0.01
        candles.append({
            "time": stamp.isoformat(), "open": price, "high": price + 0.5,
            "low": price - 0.5, "close": price + 0.1,
        })

    async def fake_mt5_candles(symbol, timeframe, limit):
        assert symbol == signal_engine.QUANTNEX_MT5_GOLD_SYMBOL
        assert timeframe == "5m"
        assert limit == 210
        return candles

    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "")
    monkeypatch.setattr(mt5_feed, "get_candles", fake_mt5_candles)
    rows, provider = asyncio.run(
        signal_engine.fetch_candles_with_provider("5min", 210, "XAUUSD")
    )
    assert provider == "MetaTrader 5 local terminal"
    assert len(rows) == 210

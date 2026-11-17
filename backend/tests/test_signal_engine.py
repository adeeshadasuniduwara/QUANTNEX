from datetime import datetime, timezone, timedelta
from app.signal_engine import aggregate_minutes, ema, rsi, atr, adx, macd, inspect_tf
from app import signal_engine


def _allow_spot_symbol(monkeypatch, allowed_symbol):
    async def valid_symbol(symbol):
        return symbol == allowed_symbol
    monkeypatch.setattr(signal_engine, "is_binance_spot_symbol", valid_symbol)

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
    _allow_spot_symbol(monkeypatch, "BTCUSDT")

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
    _allow_spot_symbol(monkeypatch, "BTCUSDT")

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
    _allow_spot_symbol(monkeypatch, "BTCUSDT")

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
    _allow_spot_symbol(monkeypatch, "BTCUSDT")

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
    _allow_spot_symbol(monkeypatch, "PEPEUSDT")

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

    async def fake_execution(_symbol):
        return {
            "best_bid": 0.000012339, "best_ask": 0.000012341, "mid_price": 0.00001234,
            "spread_bps": 1.62, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
            "tick_size": "0.00000001", "step_size": "1", "min_quantity": "1",
            "min_notional": "5", "observed_at": now.isoformat(), "provider": "Binance Spot",
        }

    monkeypatch.setattr(signal_engine, "fetch_candles_with_provider", fake_fetch)
    monkeypatch.setattr(signal_engine, "inspect_tf", bullish_analysis)
    monkeypatch.setattr(signal_engine, "get_binance_spot_execution_context", fake_execution)
    settings = {"primary": "5", "trend": "60", "enabled": ["5", "60"], "min_score": 6}
    result = asyncio.run(signal_engine.build_signal(settings, "PEPEUSDT"))
    signal = result["signal"]
    assert signal is not None
    assert 0 < signal["stop_loss"] < signal["entry"] < signal["tp1"] < signal["tp2"] < signal["tp3"]
    assert signal["entry"] > 0.00001
    assert signal["entry_type"] == "MARKET"
    assert signal["entry_price"] == signal["entry"]
    assert signal["execution_quality"]["accepted"] is True
    assert result["timeframes"]["5"]["atr"] > 0


def test_crypto_candle_provider_reports_coinbase_fallback(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine
    _allow_spot_symbol(monkeypatch, "BTCUSDT")

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


def _mock_twelve_data_candle_transport(monkeypatch, signal_engine, values):
    import httpx

    def handler(request):
        assert request.url.host == "api.twelvedata.com"
        return httpx.Response(200, json={"values": values})

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)


def _twelve_data_values(interval_seconds=300, count=220):
    now = datetime.now(timezone.utc)
    last_open = int(now.timestamp() // interval_seconds) * interval_seconds - interval_seconds
    values = []
    for index in range(count):
        stamp = datetime.fromtimestamp(last_open - index * interval_seconds, timezone.utc)
        price = 2300.0 + index * 0.01
        values.append({
            "datetime": stamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": str(price), "high": str(price + 0.5),
            "low": str(price - 0.5), "close": str(price + 0.1), "volume": "10",
        })
    return values


def test_gold_candle_provider_reports_twelve_data_when_mt5_disabled(monkeypatch):
    import asyncio
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")
    _mock_twelve_data_candle_transport(monkeypatch, signal_engine, _twelve_data_values())

    rows, provider = asyncio.run(
        signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD")
    )
    assert provider == "Twelve Data"
    assert len(rows) == 220
    assert rows == sorted(rows, key=lambda row: row["time"])


def test_gold_candle_provider_falls_back_to_twelve_data_when_mt5_disconnects(monkeypatch):
    import asyncio
    from app import mt5_feed, signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", True)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")

    async def disconnected_mt5(_symbol, _timeframe, _limit):
        raise mt5_feed.MT5FeedError("terminal is not connected")

    monkeypatch.setattr(mt5_feed, "get_candles", disconnected_mt5)
    _mock_twelve_data_candle_transport(monkeypatch, signal_engine, _twelve_data_values())

    rows, provider = asyncio.run(
        signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD")
    )
    assert provider == "Twelve Data"
    assert len(rows) == 220


def _fake_async_twelve_data_client(monkeypatch, signal_engine, values, delay=0.0):
    import asyncio

    calls = {"count": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"values": values}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            calls["count"] += 1
            if delay:
                await asyncio.sleep(delay)
            return FakeResponse()

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", FakeClient)
    return calls


def test_concurrent_gold_scans_share_one_twelve_data_request(monkeypatch):
    import asyncio
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(signal_engine, "_GOLD_CANDLE_CACHE_TTL", 45.0)
    calls = _fake_async_twelve_data_client(
        monkeypatch, signal_engine, _twelve_data_values(), delay=0.03
    )

    async def concurrent_fetches():
        return await asyncio.gather(
            signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD"),
            signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD"),
        )

    first, second = asyncio.run(concurrent_fetches())
    assert calls["count"] == 1
    assert first[0] == second[0]
    assert {first[1], second[1]} == {"Twelve Data", "Twelve Data (cached)"}


def test_expired_gold_candle_cache_triggers_new_twelve_data_request(monkeypatch):
    import asyncio
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(signal_engine, "_GOLD_CANDLE_CACHE_TTL", 0.0)
    calls = _fake_async_twelve_data_client(monkeypatch, signal_engine, _twelve_data_values())

    async def sequential_fetches():
        first = await signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD")
        second = await signal_engine.fetch_candles_with_provider("5min", 220, "XAUUSD")
        return first, second

    first, second = asyncio.run(sequential_fetches())
    assert calls["count"] == 2
    assert first[1] == "Twelve Data"
    assert second[1] == "Twelve Data"


def test_stale_twelve_data_cache_cannot_generate_a_signal(monkeypatch):
    import asyncio
    import pytest
    from app import signal_engine

    signal_engine._GOLD_CANDLE_CACHE.clear()
    monkeypatch.setattr(signal_engine, "QUANTNEX_MT5_ENABLED", False)
    monkeypatch.setattr(signal_engine, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(signal_engine, "_GOLD_CANDLE_CACHE_TTL", 45.0)
    stale_rows = candles(320)
    cache_time = signal_engine.time.monotonic()
    signal_engine._GOLD_CANDLE_CACHE[("XAUUSD", "5min", 320)] = (cache_time, stale_rows)
    signal_engine._GOLD_CANDLE_CACHE[("XAUUSD", "1h", 320)] = (cache_time, stale_rows)

    settings = {"primary": "5", "trend": "60", "enabled": ["5", "60"], "min_score": 8}
    with pytest.raises(signal_engine.MarketDataError, match="stale"):
        asyncio.run(signal_engine.build_signal(settings, "XAUUSD"))


def test_binance_exchange_info_discovers_dynamic_spot_pairs_and_filters_ineligible(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "_BINANCE_SPOT_SYMBOLS_CACHE", None)
    payload = {"symbols": [
        {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC",
         "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "1000PEPEUSDT", "status": "TRADING", "baseAsset": "1000PEPE",
         "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "OLDUSDT", "status": "BREAK", "baseAsset": "OLD",
         "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "MARGINONLYUSDT", "status": "TRADING", "baseAsset": "MARGINONLY",
         "quoteAsset": "USDT", "isSpotTradingAllowed": False},
    ]}

    def handler(request):
        assert request.url.host == "api.binance.com"
        assert request.url.path == "/api/v3/exchangeInfo"
        return httpx.Response(200, json=payload)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    symbols = asyncio.run(signal_engine.get_binance_spot_symbols())

    assert "1000PEPEUSDT" in symbols
    assert "BTCUSDT" in symbols
    assert "OLDUSDT" not in symbols
    assert "MARGINONLYUSDT" not in symbols
    assert asyncio.run(signal_engine.is_binance_spot_symbol("1000PEPEUSDT")) is True
    assert asyncio.run(signal_engine.is_binance_spot_symbol("NOT-A-PAIR")) is False


def test_newly_listed_binance_spot_pair_can_fetch_candles(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "_BINANCE_SPOT_SYMBOLS_CACHE", None)
    start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    klines = []
    for index in range(220):
        price = 0.000012 + index * 0.00000001
        open_time = start + index * 900000
        klines.append([
            open_time, str(price), str(price * 1.02), str(price * 0.98),
            str(price * 1.01), "125000", open_time + 900000 - 1,
            "500000", 100, "60000", "250000", "0",
        ])
    exchange_info = {"symbols": [{
        "symbol": "1000PEPEUSDT", "status": "TRADING",
        "baseAsset": "1000PEPE", "quoteAsset": "USDT",
        "isSpotTradingAllowed": True,
    }]}

    def handler(request):
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json=exchange_info)
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["symbol"] == "1000PEPEUSDT"
        return httpx.Response(200, json=klines)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    candles, provider = asyncio.run(
        signal_engine.fetch_candles_with_provider("15min", 220, "1000PEPEUSDT")
    )

    assert provider == "Binance Spot"
    assert len(candles) == 220
    assert candles[-1]["close"] > 0


def test_auto_signal_settings_accept_dynamic_binance_pair_names():
    import pytest
    from pydantic import ValidationError
    from app.schemas import AutoSignalSettingsRequest

    settings = AutoSignalSettingsRequest(
        enabled=True,
        interval_seconds=180,
        symbols=["1000PEPEUSDT", "BTCUSDT", "XAUUSD"],
    )
    assert settings.symbols == ["1000PEPEUSDT", "BTCUSDT", "XAUUSD"]
    with pytest.raises(ValidationError):
        AutoSignalSettingsRequest(symbols=["NOT-A-PAIR"])


def test_telegram_auto_signal_settings_keep_dynamic_binance_pairs():
    from app.telegram_worker import _normalise_auto_signal_settings

    settings = _normalise_auto_signal_settings(
        '{"enabled":true,"interval_seconds":180,"symbols":["1000PEPEUSDT","BTCUSDT","XAUUSD","bad-symbol"]}'
    )
    assert settings["enabled"] is True
    assert settings["symbols"] == ["1000PEPEUSDT", "BTCUSDT", "XAUUSD"]


def test_binance_entry_selector_prefers_market_when_spread_liquidity_and_drift_are_safe():
    from app.signal_engine import select_binance_entry

    execution = {
        "best_bid": 100.00, "best_ask": 100.02, "mid_price": 100.01,
        "spread_bps": 2.0, "bid_depth_quote": 20000.0, "ask_depth_quote": 20000.0,
    }
    selected = select_binance_entry("BUY", 100.0, 2.0, None, execution)
    assert selected is not None
    assert selected["entry_type"] == "MARKET"
    assert selected["entry_price"] == 100.02


def test_binance_entry_selector_uses_limit_at_confirmed_zone_after_price_runs():
    from app.signal_engine import select_binance_entry

    execution = {
        "best_bid": 102.00, "best_ask": 102.02, "mid_price": 102.01,
        "spread_bps": 2.0, "bid_depth_quote": 2000.0, "ask_depth_quote": 2000.0,
    }
    selected = select_binance_entry(
        "BUY", 100.0, 2.0, {"low": 101.0, "high": 101.2}, execution
    )
    assert selected is not None
    assert selected["entry_type"] == "LIMIT"
    assert selected["entry_price"] == 101.1


def test_binance_entry_selector_uses_sell_limit_above_bid_at_bearish_zone():
    from app.signal_engine import select_binance_entry

    execution = {
        "best_bid": 100.00, "best_ask": 100.02, "mid_price": 100.01,
        "spread_bps": 2.0, "bid_depth_quote": 2000.0, "ask_depth_quote": 2000.0,
    }
    selected = select_binance_entry(
        "SELL", 102.0, 2.0, {"low": 101.0, "high": 101.2}, execution
    )
    assert selected is not None
    assert selected["entry_type"] == "LIMIT"
    assert selected["entry_price"] == 101.1


def test_binance_entry_selector_rejects_wide_spread_without_valid_execution():
    from app.signal_engine import select_binance_entry

    execution = {
        "best_bid": 100.0, "best_ask": 100.8, "mid_price": 100.4,
        "spread_bps": 79.68, "bid_depth_quote": 50000.0, "ask_depth_quote": 50000.0,
    }
    assert select_binance_entry(
        "BUY", 100.0, 2.0, {"low": 99.8, "high": 100.0}, execution
    ) is None


def test_price_rounding_respects_exchange_tick_direction():
    from app.signal_engine import round_price_to_tick

    assert round_price_to_tick(0.12345678, "0.0001", round_up=True) == 0.1235
    assert round_price_to_tick(0.12345678, "0.0001", round_up=False) == 0.1234


def test_binance_execution_context_reads_exchange_filters_and_live_book(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "_BINANCE_SPOT_SYMBOLS_CACHE", None)
    exchange_info = {"symbols": [{
        "symbol": "1000PEPEUSDT", "status": "TRADING",
        "baseAsset": "1000PEPE", "quoteAsset": "USDT",
        "isSpotTradingAllowed": True,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.00000001"},
            {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }]}
    depth = {
        "bids": [["0.00001234", "100000000"], ["0.00001233", "90000000"]],
        "asks": [["0.00001235", "100000000"], ["0.00001236", "90000000"]],
    }

    def handler(request):
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json=exchange_info)
        if request.url.path == "/api/v3/ticker/bookTicker":
            return httpx.Response(200, json={
                "symbol": "1000PEPEUSDT", "bidPrice": "0.00001234",
                "bidQty": "100000000", "askPrice": "0.00001235", "askQty": "100000000",
            })
        if request.url.path == "/api/v3/depth":
            return httpx.Response(200, json=depth)
        raise AssertionError(f"Unexpected Binance endpoint: {request.url.path}")

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    context = asyncio.run(signal_engine.get_binance_spot_execution_context("1000PEPEUSDT"))

    assert context["tick_size"] == "0.00000001"
    assert context["step_size"] == "1"
    assert context["min_notional"] == "5"
    assert context["best_bid"] == 0.00001234
    assert context["best_ask"] == 0.00001235
    assert context["bid_depth_quote"] > 0
    assert context["ask_depth_quote"] > 0
    assert context["quote_asset"] == "USDT"
    assert context["quote_asset_usd_rate"] == 1.0
    assert context["bid_depth_usd"] == context["bid_depth_quote"]
    assert context["ask_depth_usd"] == context["ask_depth_quote"]


def test_binance_execution_context_converts_non_stable_quote_asset_to_usd(monkeypatch):
    import asyncio
    import httpx
    from app import signal_engine

    monkeypatch.setattr(signal_engine, "_BINANCE_SPOT_SYMBOLS_CACHE", None)
    exchange_info = {"symbols": [
        {"symbol": "ETHBTC", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "BTC",
         "isSpotTradingAllowed": True, "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.000001"}]},
        {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}]},
    ]}
    depth = {"bids": [["0.05", "1000"]], "asks": [["0.0501", "1000"]]}

    def handler(request):
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json=exchange_info)
        if request.url.path == "/api/v3/ticker/bookTicker" and request.url.params["symbol"] == "ETHBTC":
            return httpx.Response(200, json={
                "bidPrice": "0.05", "bidQty": "1000", "askPrice": "0.0501", "askQty": "1000"
            })
        if request.url.path == "/api/v3/depth":
            return httpx.Response(200, json=depth)
        if request.url.path == "/api/v3/ticker/bookTicker" and request.url.params["symbol"] == "BTCUSDT":
            return httpx.Response(200, json={
                "bidPrice": "100000", "bidQty": "10", "askPrice": "100100", "askQty": "10"
            })
        raise AssertionError(f"Unexpected Binance endpoint: {request.url.path}")

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    context = asyncio.run(signal_engine.get_binance_spot_execution_context("ETHBTC"))

    assert context["quote_asset"] == "BTC"
    assert context["quote_asset_usd_rate_source"] == "BTCUSDT"
    assert context["quote_asset_usd_rate"] == 100050
    assert context["bid_depth_usd"] > context["bid_depth_quote"]
    assert context["ask_depth_usd"] > context["ask_depth_quote"]


def test_legacy_crypto_shortlist_never_bypasses_live_spot_metadata(monkeypatch):
    import asyncio
    from app import signal_engine

    async def current_universe():
        return ["ETHUSDT"]

    monkeypatch.setattr(signal_engine, "get_binance_spot_symbols", current_universe)
    assert "BTCUSDT" in signal_engine.CRYPTO_SYMBOLS
    assert asyncio.run(signal_engine.is_binance_spot_symbol("BTCUSDT")) is False
    assert asyncio.run(signal_engine.is_binance_spot_symbol("ETHUSDT")) is True


def test_binance_spot_symbol_discovery_fails_over_to_official_market_data_host(monkeypatch):
    import asyncio
    import httpx
    from app import binance_public, signal_engine

    monkeypatch.setattr(signal_engine, "_BINANCE_SPOT_SYMBOLS_CACHE", None)
    monkeypatch.setattr(
        binance_public, "BINANCE_SPOT_PUBLIC_BASES",
        ("https://primary.test", "https://mirror.test"),
    )
    requests = []
    exchange_info = {"symbols": [{
        "symbol": "BTCUSDT", "status": "TRADING",
        "baseAsset": "BTC", "quoteAsset": "USDT",
        "isSpotTradingAllowed": True, "filters": [],
    }]}

    def handler(request):
        requests.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(503, json={"msg": "temporary host outage"})
        return httpx.Response(200, json=exchange_info)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(signal_engine.httpx, "AsyncClient", mock_client)
    symbols = asyncio.run(signal_engine.get_binance_spot_symbols(force_refresh=True))

    assert symbols == ["BTCUSDT"]
    assert requests == ["primary.test", "mirror.test"]

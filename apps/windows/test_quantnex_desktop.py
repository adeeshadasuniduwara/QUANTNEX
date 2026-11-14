import io
import json
import unittest
import urllib.error

import quantnex_desktop as desktop


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class WindowsChartDataTests(unittest.TestCase):
    def test_btc_chart_uses_binance_spot_candles(self):
        payload = [
            [1, "65000", "65100", "64900", "65050"],
            [2, "65050", "65200", "65000", "65150"],
        ]
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return FakeResponse(payload)

        candles, price, provider = desktop.fetch_chart_data("BTCUSDT", urlopen=opener)

        self.assertIn("api.binance.com/api/v3/klines", seen["url"])
        self.assertEqual(seen["timeout"], 12)
        self.assertEqual(provider, "Binance Spot")
        self.assertEqual(len(candles), 2)
        self.assertEqual(price, 65150.0)

    def test_gold_chart_uses_local_read_only_mt5_api_and_configured_symbol(self):
        payload = {
            "symbol": "XAUUSD.a",
            "interval": "15m",
            "provider": "MetaTrader 5 local terminal",
            "mode": "read_only_market_data",
            "orders_enabled": False,
            "candles": [
                {"time": "2026-11-14T00:00:00+00:00", "open": 2300, "high": 2302, "low": 2299, "close": 2301},
                {"time": "2026-11-14T00:15:00+00:00", "open": 2301, "high": 2304, "low": 2300, "close": 2303},
            ],
        }
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            return FakeResponse(payload)

        candles, price, provider = desktop.fetch_chart_data("XAUUSD", urlopen=opener)

        self.assertIn("127.0.0.1:8000/api/v1/market/mt5/candles", seen["url"])
        self.assertNotIn("symbol=XAUUSD", seen["url"])
        self.assertIn("interval=15m&limit=250", seen["url"])
        self.assertEqual(provider, "MetaTrader 5 local terminal")
        self.assertEqual(candles[-1]["close"], 2303.0)
        self.assertEqual(price, 2303.0)

    def test_gold_chart_rejects_response_that_does_not_confirm_read_only_mode(self):
        payload = {"orders_enabled": True, "mode": "trading", "candles": []}
        with self.assertRaisesRegex(RuntimeError, "read-only market-data mode"):
            desktop.fetch_chart_data("XAUUSD", urlopen=lambda *_args, **_kwargs: FakeResponse(payload))

    def test_provider_http_error_is_shown_as_actionable_detail(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 503, "Unavailable", {},
                io.BytesIO(b'{"detail":"MT5 terminal is not connected."}')
            )

        with self.assertRaisesRegex(RuntimeError, "MT5 terminal is not connected"):
            desktop.fetch_chart_data("XAUUSD", urlopen=opener)

    def test_unsupported_chart_symbol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "BTCUSDT and XAUUSD"):
            desktop.fetch_chart_data("EURUSD", urlopen=lambda *_args, **_kwargs: self.fail("No network call expected"))


if __name__ == "__main__":
    unittest.main()

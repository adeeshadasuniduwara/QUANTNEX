import hashlib
import io
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

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


class FakeStreamResponse:
    def __init__(self, body):
        self.body = body
        self.offset = 0
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class WindowsUpdaterIntegrityTests(unittest.TestCase):
    ASSET_URL = "https://github.com/owner/QUANTNEX/releases/download/v1/QUANTNEX.exe"
    CHECKSUM_URL = "https://github.com/owner/QUANTNEX/releases/download/v1/SHA256SUMS.txt"

    def test_only_https_github_release_asset_urls_are_trusted(self):
        self.assertTrue(desktop.is_trusted_release_asset_url(self.ASSET_URL))
        self.assertFalse(desktop.is_trusted_release_asset_url("http://github.com/owner/QUANTNEX/releases/download/v1/QUANTNEX.exe"))
        self.assertFalse(desktop.is_trusted_release_asset_url("https://example.com/releases/download/v1/QUANTNEX.exe"))
        self.assertFalse(desktop.is_trusted_release_asset_url("https://github.com/owner/QUANTNEX/blob/main/QUANTNEX.exe"))
        self.assertFalse(desktop.is_trusted_release_asset_url("https://user:pass@github.com/owner/QUANTNEX/releases/download/v1/QUANTNEX.exe"))

    def test_checksum_matches_exact_filename_only(self):
        digest = "a" * 64
        self.assertEqual(desktop.expected_release_checksum(digest + "  QUANTNEX.exe", "QUANTNEX.exe"), digest)
        self.assertIsNone(desktop.expected_release_checksum(digest + "  old-QUANTNEX.exe", "QUANTNEX.exe"))
        self.assertIsNone(desktop.expected_release_checksum("bad-hash  QUANTNEX.exe", "QUANTNEX.exe"))

    def test_valid_exe_is_verified_then_atomically_staged(self):
        payload = b"Q" * 120000
        digest = hashlib.sha256(payload).hexdigest()
        manifest = (digest + "  QUANTNEX.exe\n").encode("utf-8")
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return FakeStreamResponse(payload if request.full_url == self.ASSET_URL else manifest)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "updates" / "QUANTNEX.exe"
            destination.parent.mkdir()
            destination.write_bytes(b"previous verified EXE")
            result = desktop.stage_verified_release_exe(
                self.ASSET_URL, self.CHECKSUM_URL, destination,
                urlopen=opener, max_bytes=200000, min_bytes=100000
            )
            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(destination.with_name("QUANTNEX.exe.part").exists())
        self.assertEqual(calls, [self.ASSET_URL, self.CHECKSUM_URL])

    def test_checksum_mismatch_preserves_previous_staged_exe(self):
        payload = b"N" * 120000
        manifest = ("0" * 64 + "  QUANTNEX.exe\n").encode("utf-8")

        def opener(request, timeout):
            return FakeStreamResponse(payload if request.full_url == self.ASSET_URL else manifest)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "QUANTNEX.exe"
            destination.write_bytes(b"previous verified EXE")
            with self.assertRaisesRegex(ValueError, "SHA256 verification failed"):
                desktop.stage_verified_release_exe(
                    self.ASSET_URL, self.CHECKSUM_URL, destination,
                    urlopen=opener, max_bytes=200000, min_bytes=100000
                )
            self.assertEqual(destination.read_bytes(), b"previous verified EXE")
            self.assertFalse(destination.with_name("QUANTNEX.exe.part").exists())

    def test_oversized_download_is_rejected_and_partial_removed(self):
        payload = b"X" * 1000

        def opener(request, timeout):
            return FakeStreamResponse(payload)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "QUANTNEX.exe"
            with self.assertRaisesRegex(ValueError, "200 MB safety limit"):
                desktop.stage_verified_release_exe(
                    self.ASSET_URL, self.CHECKSUM_URL, destination,
                    urlopen=opener, max_bytes=100, min_bytes=1
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name("QUANTNEX.exe.part").exists())

    def test_untrusted_url_is_rejected_before_network_access(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "QUANTNEX.exe"
            with self.assertRaisesRegex(ValueError, "official HTTPS GitHub"):
                desktop.stage_verified_release_exe(
                    "https://example.com/QUANTNEX.exe", self.CHECKSUM_URL, destination,
                    urlopen=lambda *_args, **_kwargs: self.fail("Network must not be called")
                )
            self.assertFalse(destination.exists())






class WindowsWalletValidationTests(unittest.TestCase):
    def test_accepts_only_finite_positive_wallet_amounts_within_api_limit(self):
        self.assertEqual(desktop.validate_wallet_amount("10.25"), 10.25)
        for value in ("", "not-a-number", "0", "-1", "nan", "inf", "-inf", "1000000001"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    desktop.validate_wallet_amount(value)



class WindowsJournalSyncTests(unittest.TestCase):
    def test_new_local_trades_are_pending_then_persist_as_synced(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(desktop, "app_data", return_value=Path(directory)):
            journal = desktop.TradeJournal()
            local_id = journal.add("XAUUSD", "Buy", "Win", 25.0, "test note")
            pending = journal.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0][0], local_id)
            self.assertEqual(journal.unknown_sync_count(), 0)

            journal.mark_synced(local_id)
            self.assertEqual(journal.pending(), [])
            restarted = desktop.TradeJournal()
            self.assertEqual(restarted.recent()[0][5], "SYNCED")

    def test_legacy_rows_are_unknown_and_not_automatically_replayed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(desktop, "app_data", return_value=Path(directory)):
            database = Path(directory) / "journal.sqlite3"
            with closing(sqlite3.connect(database)) as db:
                with db:
                    db.execute("""CREATE TABLE trades(
                        id INTEGER PRIMARY KEY, created TEXT NOT NULL, symbol TEXT NOT NULL,
                        side TEXT NOT NULL, outcome TEXT NOT NULL, pnl REAL NOT NULL, notes TEXT NOT NULL)""")
                    db.execute(
                        "INSERT INTO trades(created,symbol,side,outcome,pnl,notes) VALUES(?,?,?,?,?,?)",
                        ("2026-11-14T00:00:00+00:00", "BTCUSDT", "Buy", "Win", 10.0, "old row")
                    )

            journal = desktop.TradeJournal()
            self.assertEqual(journal.pending(), [])
            self.assertEqual(journal.unknown_sync_count(), 1)
            self.assertEqual(journal.recent()[0][5], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()

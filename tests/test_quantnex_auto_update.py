"""Offline tests for the local updater's per-workspace Telegram receipt."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "web"))

import quantnex_local_server as updater  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class TelegramUpdateNoticeTests(unittest.TestCase):
    SHA = "a" * 40

    def test_sends_only_a_local_api_request_and_reports_success(self):
        response = FakeResponse(b'{"ok": true, "message_id": 12}')
        with patch.object(updater.urllib.request, "urlopen", return_value=response) as urlopen:
            sent = updater.notify_connected_telegram({
                "sha": self.SHA,
                "message": "feat: automatic updater",
            })

        self.assertTrue(sent)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/v1/telegram/notify")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data.decode("utf-8"))
        self.assertIn("main@aaaaaaa", body["message"])
        self.assertIn("automatic updater", body["message"])
        self.assertNotIn("bot_token", body)

    def test_missing_connected_bot_is_a_safe_opt_out(self):
        error = HTTPError(
            "http://127.0.0.1:8000/api/v1/telegram/notify",
            409,
            "Conflict",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"Connect your Telegram bot first."}'),
        )
        with patch.object(updater.urllib.request, "urlopen", side_effect=error) as urlopen:
            sent = updater.notify_connected_telegram({"sha": self.SHA, "message": "update"})

        self.assertFalse(sent)
        self.assertEqual(urlopen.call_count, 1)

    def test_retries_until_the_local_api_is_ready(self):
        response = FakeResponse(b'{"ok": true}')
        with patch.object(
            updater.urllib.request,
            "urlopen",
            side_effect=[URLError("API starting"), response],
        ) as urlopen, patch.object(updater.time, "sleep"):
            sent = updater.notify_connected_telegram({"sha": self.SHA, "message": "fix: update"})

        self.assertTrue(sent)
        self.assertEqual(urlopen.call_count, 2)

    def test_invalid_commit_is_never_sent(self):
        with patch.object(updater.urllib.request, "urlopen") as urlopen:
            sent = updater.notify_connected_telegram({"sha": "not-a-sha", "message": "bad"})

        self.assertFalse(sent)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the loopback Web source updater's archive safety."""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "apps" / "web" / "quantnex_local_server.py"
SPEC = importlib.util.spec_from_file_location("quantnex_local_server_under_test", MODULE_PATH)
UPDATER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(UPDATER)


class FakeResponse:
    def __init__(self, body: bytes, content_length: str | None = None):
        self.stream = io.BytesIO(body)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.stream.read(size)


class WebSourceUpdaterDownloadTests(unittest.TestCase):
    def test_rejects_advertised_archive_larger_than_limit_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source.zip"
            response = FakeResponse(b"unused", content_length="101")
            with patch.object(UPDATER.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "100 MB"):
                    UPDATER.download_bounded_archive("https://example.invalid/archive.zip", destination, max_bytes=100)
            self.assertFalse(destination.exists())

    def test_rejects_stream_that_exceeds_limit_and_removes_partial_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source.zip"
            body = b"x" * (1024 * 1024 + 1)
            response = FakeResponse(body)
            with patch.object(UPDATER.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "100 MB"):
                    UPDATER.download_bounded_archive(
                        "https://example.invalid/archive.zip", destination, max_bytes=1024 * 1024
                    )
            self.assertFalse(destination.exists())

    def test_rejects_invalid_content_length_and_empty_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source.zip"
            for response in (FakeResponse(b"data", "unknown"), FakeResponse(b"")):
                with patch.object(UPDATER.urllib.request, "urlopen", return_value=response):
                    with self.assertRaises(RuntimeError):
                        UPDATER.download_bounded_archive("https://example.invalid/archive.zip", destination)
                self.assertFalse(destination.exists())

    def test_accepts_valid_archive_within_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source.zip"
            response = FakeResponse(b"zip-bytes", content_length="9")
            with patch.object(UPDATER.urllib.request, "urlopen", return_value=response):
                written = UPDATER.download_bounded_archive(
                    "https://example.invalid/archive.zip", destination, max_bytes=100
                )
            self.assertEqual(written, 9)
            self.assertEqual(destination.read_bytes(), b"zip-bytes")

    def test_archive_paths_reject_traversal_and_windows_path_syntax(self):
        self.assertIsNone(UPDATER._safe_web_relative(("..", "outside.txt")))
        self.assertIsNone(UPDATER._safe_web_relative(("folder\\outside.txt",)))
        self.assertIsNone(UPDATER._safe_web_relative(("C:", "outside.txt")))
        self.assertEqual(str(UPDATER._safe_web_relative(("index.html",))), "index.html")



    def test_sidebar_labels_are_compact_and_never_wrap_into_multiple_lines(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        css = (root / "apps" / "web" / "workspace-polish.css").read_text(encoding="utf-8")
        html = (root / "apps" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".sidebar .sidebar-nav .nav-link{", css)
        self.assertIn("font-size:9.5px;", css)
        self.assertIn("white-space:nowrap;", css)
        self.assertIn("text-overflow:ellipsis;", css)
        self.assertIn("flex-wrap:nowrap;", css)
        self.assertIn("workspace-polish.css?v=20261116-sidebar-compact1", html)

class GitHubApiCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_file = Path(self.temp_dir.name) / "data" / "updates" / "github_api_cache.json"
        self.cache_file.parent.mkdir(parents=True)
        self.cache_patch = patch.object(UPDATER, "API_CACHE_FILE", self.cache_file)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_repeated_status_checks_reuse_persistent_response(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        calls = []

        def respond(request, timeout):
            calls.append(request.full_url)
            return FakeResponse(b'{"sha":"fresh"}')

        with patch.object(UPDATER.urllib.request, "urlopen", side_effect=respond):
            self.assertEqual(UPDATER.github_json(url), {"sha": "fresh"})
            self.assertEqual(UPDATER.github_json(url), {"sha": "fresh"})

        self.assertEqual(calls, [url])
        self.assertTrue(self.cache_file.is_file())

    def test_expired_and_malformed_timestamps_refresh_safely(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        for fetched_at in (1, "not-a-timestamp"):
            self.cache_file.write_text(json.dumps({
                url: {"fetched_at": fetched_at, "data": {"sha": "old"}}
            }), encoding="utf-8")
            with patch.object(
                UPDATER.urllib.request, "urlopen",
                return_value=FakeResponse(b'{"sha":"fresh"}'),
            ) as request:
                self.assertEqual(UPDATER.github_json(url), {"sha": "fresh"})
                request.assert_called_once()

    def test_stale_cache_fallback_handles_403_and_429_within_retention(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        for status_code in (403, 429):
            self.cache_file.write_text(json.dumps({
                url: {
                    "fetched_at": time.time() - UPDATER.API_CACHE_MAX_AGE_SECONDS + 60,
                    "data": {"sha": "last-known-good"},
                }
            }), encoding="utf-8")

            def rate_limited(request, timeout):
                raise urllib.error.HTTPError(
                    request.full_url, status_code, "rate limit exceeded", {}, None
                )

            with patch.object(UPDATER.urllib.request, "urlopen", side_effect=rate_limited):
                self.assertEqual(
                    UPDATER.github_json(url),
                    {"sha": "last-known-good"},
                )

    def test_stale_cache_fallback_rejects_entries_beyond_retention(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        for status_code in (403, 429):
            self.cache_file.write_text(json.dumps({
                url: {
                    "fetched_at": time.time() - UPDATER.API_CACHE_MAX_AGE_SECONDS - 1,
                    "data": {"sha": "too-old"},
                }
            }), encoding="utf-8")

            def rate_limited(request, timeout):
                raise urllib.error.HTTPError(
                    request.full_url, status_code, "rate limit exceeded", {}, None
                )

            with patch.object(UPDATER.urllib.request, "urlopen", side_effect=rate_limited):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    UPDATER.github_json(url)
                self.assertEqual(caught.exception.code, status_code)


    def test_etag_conditional_request_reuses_cached_payload_on_304(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        self.cache_file.write_text(json.dumps({
            url: {
                "fetched_at": time.time() - UPDATER.API_CACHE_TTL_SECONDS - 1,
                "data": {"sha": "cached"},
                "etag": '"abc123"',
            }
        }), encoding="utf-8")
        error = urllib.error.HTTPError(
            url, 304, "Not Modified", {"ETag": '"abc123"'}, None
        )
        with patch.object(UPDATER.urllib.request, "urlopen", side_effect=error) as request:
            self.assertEqual(UPDATER.github_json(url), {"sha": "cached"})
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_header("If-none-match"), '"abc123"')
        saved = json.loads(self.cache_file.read_text(encoding="utf-8"))[url]
        self.assertGreater(saved["fetched_at"], time.time() - 5)

    def test_retry_after_prevents_repeated_rate_limit_requests(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        self.cache_file.write_text(json.dumps({
            url: {
                "fetched_at": time.time() - UPDATER.API_CACHE_TTL_SECONDS - 1,
                "data": {"sha": "last-known-good"},
            }
        }), encoding="utf-8")
        error = urllib.error.HTTPError(
            url, 429, "Too Many Requests", {"Retry-After": "300"}, None
        )
        with patch.object(UPDATER.urllib.request, "urlopen", side_effect=error) as request:
            self.assertEqual(UPDATER.github_json(url), {"sha": "last-known-good"})
            self.assertEqual(UPDATER.github_json(url), {"sha": "last-known-good"})
            request.assert_called_once()
        saved = json.loads(self.cache_file.read_text(encoding="utf-8"))[url]
        self.assertGreater(saved["retry_after"], time.time())

    def test_non_rate_limit_403_does_not_hide_permission_errors(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        self.cache_file.write_text(json.dumps({
            url: {
                "fetched_at": time.time() - UPDATER.API_CACHE_TTL_SECONDS - 1,
                "data": {"sha": "stale"},
            }
        }), encoding="utf-8")
        error = urllib.error.HTTPError(
            url, 403, "Forbidden", {"X-RateLimit-Remaining": "42"}, None
        )
        with patch.object(UPDATER.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                UPDATER.github_json(url)
        self.assertEqual(caught.exception.code, 403)

    def test_stale_cache_is_reused_during_server_errors_with_backoff(self):
        url = "https://api.github.com/repos/example/project/commits/main"
        self.cache_file.write_text(json.dumps({
            url: {
                "fetched_at": time.time() - UPDATER.API_CACHE_TTL_SECONDS - 1,
                "data": {"sha": "last-known-good"},
            }
        }), encoding="utf-8")
        error = urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
        with patch.object(UPDATER.urllib.request, "urlopen", side_effect=error) as request:
            self.assertEqual(UPDATER.github_json(url), {"sha": "last-known-good"})
            self.assertEqual(UPDATER.github_json(url), {"sha": "last-known-good"})
            request.assert_called_once()


if __name__ == "__main__":
    unittest.main()

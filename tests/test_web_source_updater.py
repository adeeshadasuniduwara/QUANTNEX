"""Regression tests for the loopback Web source updater's archive safety."""
from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

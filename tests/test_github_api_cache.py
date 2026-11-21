import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.github_api_cache import github_json_cached


class _Headers(dict):
    pass


class _Response:
    def __init__(self, payload, headers=None):
        self.payload = json.dumps(payload).encode()
        self.headers = _Headers(headers or {})
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.payload


class GithubApiCacheTests(unittest.TestCase):
    def test_etag_is_sent_and_304_reuses_cached_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            url = "https://api.github.com/repos/example/repo/commits/main"
            with patch("backend.app.github_api_cache.urllib.request.urlopen", return_value=_Response(
                {"sha": "a" * 40}, {"ETag": '"abc"'}
            )) as request:
                first = github_json_cached(url, cache, "test", fresh_seconds=0)
                self.assertEqual(first["sha"], "a" * 40)
                request.reset_mock()
                from urllib.error import HTTPError
                error = HTTPError(url, 304, "Not Modified", _Headers({}), None)
                request.side_effect = error
                second = github_json_cached(url, cache, "test", fresh_seconds=0)
                self.assertEqual(second, first)
                sent = request.call_args.args[0]
                self.assertEqual(sent.get_header("If-none-match"), '"abc"')

    def test_rate_limit_uses_cached_latest_commit_without_repeating_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            url = "https://api.github.com/repos/example/repo/commits/main"
            with patch("backend.app.github_api_cache.urllib.request.urlopen", return_value=_Response(
                {"sha": "b" * 40}, {"ETag": '"latest"'}
            )):
                first = github_json_cached(url, cache, "test", fresh_seconds=0)
            from urllib.error import HTTPError
            rate_limit = HTTPError(url, 403, "Forbidden",
                _Headers({"X-RateLimit-Remaining": "0", "Retry-After": "120"}), None)
            with patch("backend.app.github_api_cache.urllib.request.urlopen", side_effect=rate_limit) as request:
                second = github_json_cached(url, cache, "test", fresh_seconds=0)
                third = github_json_cached(url, cache, "test", fresh_seconds=0)
                self.assertEqual(second, first)
                self.assertEqual(third, first)
                self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()

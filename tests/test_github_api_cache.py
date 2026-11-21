import json
import urllib.error

import quantnex_updater as updater


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_github_api_response_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "quantnex_updater.py"))
    calls = []
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda request, timeout: (calls.append(request.full_url) or FakeResponse({"sha": "abc"})))
    url = "https://api.github.com/repos/example/project/commits/main"

    assert updater._request_json(url) == {"sha": "abc"}
    assert updater._request_json(url) == {"sha": "abc"}
    assert calls == [url]


def test_rate_limit_uses_stale_cached_response(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "quantnex_updater.py"))
    cache_path = tmp_path / updater.API_CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({
        "https://api.github.com/repos/example/project/commits/main": {
            "fetched_at": 1,
            "data": {"sha": "last-known-good"}
        }
    }), encoding="utf-8")

    def rate_limited(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "rate limit exceeded", {}, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", rate_limited)
    assert updater._request_json(
        "https://api.github.com/repos/example/project/commits/main"
    ) == {"sha": "last-known-good"}


def test_expired_cache_refreshes_from_github(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "quantnex_updater.py"))
    url = "https://api.github.com/repos/example/project/commits/main"
    cache_path = tmp_path / updater.API_CACHE_RELATIVE
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({url: {"fetched_at": 1, "data": {"sha": "old"}}}), encoding="utf-8")
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda request, timeout: FakeResponse({"sha": "new"}))

    assert updater._request_json(url) == {"sha": "new"}

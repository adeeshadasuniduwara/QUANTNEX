"""Conditional, cached GitHub API reads with rate-limit backoff and stale fallback."""
from __future__ import annotations

import email.utils
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_DEFAULT_FRESH_SECONDS = 60
_DEFAULT_STALE_SECONDS = 24 * 60 * 60


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _retry_timestamp(headers: Any, failures: int) -> float:
    now = time.time()
    retry_after = str(headers.get("Retry-After", "") or "").strip()
    if retry_after:
        try:
            return now + max(1.0, min(24 * 60 * 60, float(retry_after)))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                return max(now + 1.0, parsed.timestamp())
            except (TypeError, ValueError, OverflowError):
                pass
    reset = str(headers.get("X-RateLimit-Reset", "") or "").strip()
    if reset:
        try:
            stamp = float(reset)
            if stamp > now:
                return stamp
        except ValueError:
            pass
    return now + min(60 * 60, 30 * (2 ** min(max(failures - 1, 0), 7)))


def _is_rate_limited(error: urllib.error.HTTPError) -> bool:
    if error.code == 429:
        return True
    if error.code != 403:
        return False
    remaining = str(error.headers.get("X-RateLimit-Remaining", "") or "").strip()
    try:
        if int(remaining) == 0:
            return True
    except ValueError:
        pass
    try:
        body = error.read(4096).decode("utf-8", "replace").lower()
    except Exception:
        body = ""
    return "rate limit" in body or "secondary rate" in body


def github_json_cached(
    url: str,
    cache_file: str | Path,
    user_agent: str,
    *,
    fresh_seconds: int = _DEFAULT_FRESH_SECONDS,
    stale_seconds: int = _DEFAULT_STALE_SECONDS,
    timeout: int = 25,
) -> dict[str, Any]:
    """GET one GitHub API JSON resource once per cache window.

    Uses ETag/Last-Modified validators, honours Retry-After and X-RateLimit-Reset,
    serializes concurrent callers, and serves a bounded last-known-good response
    during transient failures or GitHub rate limiting.
    """
    if not url.startswith("https://api.github.com/"):
        raise ValueError("Only GitHub API URLs can use the shared API cache.")
    path = Path(cache_file)
    key = url
    with _LOCK:
        cache = _read_cache(path)
        entry = cache.get(key)
        if not isinstance(entry, dict):
            entry = {}
        now = time.time()
        payload = entry.get("payload")
        fetched_at = float(entry.get("fetched_at") or 0)
        cached_valid = isinstance(payload, dict) and now - fetched_at <= stale_seconds
        if cached_valid and now - fetched_at < fresh_seconds:
            return payload
        retry_at = float(entry.get("retry_after") or 0)
        if cached_valid and now < retry_at:
            return payload

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if entry.get("etag"):
            headers["If-None-Match"] = str(entry["etag"])
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = str(entry["last_modified"])
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise RuntimeError("GitHub returned an invalid update response.")
                entry = {
                    "payload": result,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "fetched_at": time.time(),
                    "retry_after": 0,
                    "failures": 0,
                }
                cache[key] = entry
                _write_cache(path, cache)
                return result
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and cached_valid:
                entry["fetched_at"] = time.time()
                entry["retry_after"] = 0
                entry["failures"] = 0
                cache[key] = entry
                _write_cache(path, cache)
                return payload
            failures = int(entry.get("failures") or 0) + 1
            if _is_rate_limited(exc):
                entry["failures"] = failures
                entry["retry_after"] = _retry_timestamp(exc.headers, failures)
                cache[key] = entry
                _write_cache(path, cache)
                if cached_valid:
                    return payload
                raise RuntimeError(
                    "GitHub API rate limit reached; no cached response is available. "
                    "QUANTNEX will retry after the server-provided reset window."
                ) from exc
            if cached_valid and exc.code >= 500:
                return payload
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            if cached_valid:
                return payload
            raise RuntimeError("GitHub API is temporarily unavailable and no cached response exists.") from exc

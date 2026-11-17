"""Failover-aware client for Binance public Spot REST market-data endpoints.

Only public market-data routes under /api/v3 are allowed here. No API key,
account endpoint, signed request, or order endpoint is used.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit
from typing import Any, Sequence
from weakref import WeakKeyDictionary

import httpx

# Binance documents these public REST hosts. The dedicated market-data host is
# preferred; api1-api4 are last because Binance notes they are less stable.
BINANCE_SPOT_PUBLIC_BASES: tuple[str, ...] = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
)

_REQUEST_SEMAPHORES: WeakKeyDictionary = WeakKeyDictionary()
_PREFERRED_BASES: WeakKeyDictionary = WeakKeyDictionary()
_RETRYABLE_HTTP_STATUSES = {408, 425}


def _request_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _REQUEST_SEMAPHORES.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(4)
        _REQUEST_SEMAPHORES[loop] = semaphore
    return semaphore


def _ordered_bases(bases: tuple[str, ...]) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    preferred = _PREFERRED_BASES.get(loop)
    if preferred in bases:
        return (preferred, *(base for base in bases if base != preferred))
    return bases


class BinancePublicDataError(RuntimeError):
    """A public market-data request failed or was rejected by Binance."""

    def __init__(
        self,
        path: str,
        attempts: Sequence[str],
        *,
        status_code: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        self.path = path
        self.attempts = tuple(attempts)
        self.status_code = status_code
        self.retry_after = retry_after
        detail = "; ".join(self.attempts) or "no endpoint attempts were made"
        super().__init__(f"Binance public request {path} failed: {detail}")


def _response_detail(base: str, response: httpx.Response) -> str:
    detail = f"{base}: HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code")
        message = payload.get("msg") or payload.get("message")
        if code is not None:
            detail += f" code={code}"
        if message:
            detail += f" {str(message)[:160]}"
    return detail


def _validated_bases(base_urls: Sequence[str] | None) -> tuple[str, ...]:
    bases = tuple(BINANCE_SPOT_PUBLIC_BASES if base_urls is None else base_urls)
    normalized: list[str] = []
    for base in bases:
        value = str(base).rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Binance public base URLs must be HTTPS origins.")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("At least one Binance public base URL is required.")
    return tuple(normalized)


async def get_binance_public_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    base_urls: Sequence[str] | None = None,
) -> tuple[Any, str]:
    """GET a public Spot market-data route with safe host failover.

    Transport failures, invalid JSON, HTTP 408/425 and server errors try
    the next documented host. 403/451 WAF or geo restrictions and 418/429
    rate limits stop immediately; ordinary 4xx validation errors also stop.
    Returns (decoded_json, successful_base_url).
    """
    if (
        not isinstance(path, str)
        or not re.fullmatch(r"/api/v3/[A-Za-z0-9/]+", path)
        or ".." in path.split("/")
    ):
        raise ValueError("Only Binance public Spot /api/v3 routes are allowed.")
    bases = _ordered_bases(_validated_bases(base_urls))
    loop = asyncio.get_running_loop()
    attempts: list[str] = []

    for base in bases:
        try:
            async with _request_semaphore():
                response = await client.get(
                    f"{base}{path}", params=params,
                    timeout=httpx.Timeout(3.5, connect=1.5),
                )
            if response.status_code in {418, 429}:
                detail = _response_detail(base, response)
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    detail += f" Retry-After={retry_after}"
                raise BinancePublicDataError(
                    path, [*attempts, detail],
                    status_code=response.status_code,
                    retry_after=retry_after,
                )
            if 400 <= response.status_code < 500 and response.status_code not in _RETRYABLE_HTTP_STATUSES:
                raise BinancePublicDataError(
                    path, [*attempts, _response_detail(base, response)],
                    status_code=response.status_code,
                )
            response.raise_for_status()
            try:
                payload = response.json()
                _PREFERRED_BASES[loop] = base
                return payload, base
            except ValueError as exc:
                attempts.append(f"{base}: invalid JSON ({type(exc).__name__})")
        except BinancePublicDataError:
            raise
        except httpx.HTTPStatusError as exc:
            attempts.append(_response_detail(base, exc.response))
        except httpx.HTTPError as exc:
            attempts.append(f"{base}: {type(exc).__name__}")
        except ValueError as exc:
            attempts.append(f"{base}: invalid response ({type(exc).__name__})")

    raise BinancePublicDataError(path, attempts)

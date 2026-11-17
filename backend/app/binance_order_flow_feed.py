"""Read-only Binance Spot REST collector for source-aware order-flow snapshots.

This module intentionally fetches recent aggregate trades and a separate L2
snapshot. It does NOT claim a sequenced/continuous order book; that requires
the Binance WebSocket diff-depth snapshot-bridging procedure.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .order_flow import calculate_order_flow

BINANCE_SPOT_BASE = "https://api.binance.com"
_REQUEST_SLOTS = asyncio.Semaphore(4)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,25}$")


class BinanceOrderFlowFeedError(RuntimeError):
    """Raised when public market data cannot safely produce an order-flow snapshot."""


async def _get_json(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    try:
        async with _REQUEST_SLOTS:
            response = await client.get(f"{BINANCE_SPOT_BASE}{path}", params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BinanceOrderFlowFeedError(f"Binance public endpoint failed: {path}") from exc


async def fetch_spot_order_flow(
    client: httpx.AsyncClient,
    symbol: str,
    *,
    tick_size: str,
    now: datetime | None = None,
    max_trade_age_seconds: float = 15.0,
    trade_limit: int = 1000,
    depth_limit: int = 100,
) -> dict[str, Any]:
    """Fetch current Spot aggTrades + independent depth snapshot and calculate metrics.

    tick_size must come from the symbol's current exchangeInfo PRICE_FILTER.
    No API key is used. A stale trade window or invalid book fails closed.
    """
    if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol):
        raise BinanceOrderFlowFeedError("Invalid Binance Spot symbol.")
    if isinstance(trade_limit, bool) or not isinstance(trade_limit, int) or not 1 <= trade_limit <= 1000:
        raise BinanceOrderFlowFeedError("trade_limit must be between 1 and 1000.")
    if depth_limit not in (5, 10, 20, 50, 100, 500, 1000):
        raise BinanceOrderFlowFeedError("Unsupported Binance depth limit.")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise BinanceOrderFlowFeedError("now must be timezone-aware.")

    session_start = clock.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    trades_task = _get_json(client, "/api/v3/aggTrades", {"symbol": symbol, "limit": trade_limit})
    depth_task = _get_json(client, "/api/v3/depth", {"symbol": symbol, "limit": depth_limit})
    session_probe_task = _get_json(client, "/api/v3/aggTrades", {
        "symbol": symbol, "startTime": int(session_start.timestamp() * 1000), "limit": 1,
    })
    trades, depth, session_probe = await asyncio.gather(
        trades_task, depth_task, session_probe_task
    )
    observed_at = datetime.now(timezone.utc)
    if not isinstance(trades, list) or not trades:
        raise BinanceOrderFlowFeedError("Binance returned no aggregate trades.")
    if not isinstance(depth, dict) or not isinstance(depth.get("bids"), list) or not isinstance(depth.get("asks"), list):
        raise BinanceOrderFlowFeedError("Binance returned an invalid depth snapshot.")
    try:
        last_update_id = int(depth["lastUpdateId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BinanceOrderFlowFeedError("Depth snapshot is missing lastUpdateId.") from exc
    if last_update_id < 0:
        raise BinanceOrderFlowFeedError("Depth snapshot has an invalid update ID.")
    session_start_trade_id = None
    session_start_probe_at = None
    if isinstance(session_probe, list) and session_probe:
        try:
            session_start_trade_id = int(session_probe[0]["a"])
            session_start_probe_ms = int(session_probe[0]["T"])
            session_start_probe_at = datetime.fromtimestamp(
                session_start_probe_ms / 1000, timezone.utc
            ).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BinanceOrderFlowFeedError("UTC session-start trade probe is malformed.") from exc
        if session_start_trade_id < 0 or session_start_probe_ms < int(session_start.timestamp() * 1000):
            raise BinanceOrderFlowFeedError("UTC session-start trade probe is invalid.")
        if session_start_probe_ms > int(clock.timestamp() * 1000) + 2000:
            raise BinanceOrderFlowFeedError("UTC session-start trade probe is future-dated.")
        for row in trades:
            if not isinstance(row, dict) or str(row.get("a")) != str(session_start_trade_id):
                continue
            try:
                recent_probe_ms = int(row["T"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise BinanceOrderFlowFeedError(
                    "Recent session-start trade row is malformed."
                ) from exc
            if recent_probe_ms != session_start_probe_ms:
                raise BinanceOrderFlowFeedError(
                    "UTC session-start probe conflicts with the recent trade response."
                )
            break
    elif not isinstance(session_probe, list):
        raise BinanceOrderFlowFeedError("UTC session-start trade probe is invalid.")

    try:
        metrics = calculate_order_flow(
            trades,
            depth["bids"],
            depth["asks"],
            now=clock,
            max_trade_age_seconds=max_trade_age_seconds,
            tick_size=tick_size,
            session_start_trade_id=session_start_trade_id,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise BinanceOrderFlowFeedError(f"Order-flow data rejected: {exc}") from exc

    metrics.update({
        "symbol": symbol,
        "market_type": "BINANCE_SPOT",
        "depth_snapshot_update_id": last_update_id,
        "depth_is_continuous": False,
        "depth_observed_at": observed_at.isoformat(),
        "session_start_probe_at": session_start_probe_at,
        "feed_mode": "PUBLIC_REST_SNAPSHOT",
    })
    return metrics
